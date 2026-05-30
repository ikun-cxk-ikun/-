require('dotenv').config();
const express = require('express');
const http = require('http');
const { Server } = require('socket.io');
const path = require('path');
const fs = require('fs');

// 创建Express应用
const app = express();
const server = http.createServer(app);
const io = new Server(server);

// 静态文件服务
app.use(express.static(path.join(__dirname, 'public')));

// 车辆仿真模块
const VehicleSimulation = require('./src/simulation/VehicleSimulation');
const simulation = new VehicleSimulation(io);

// API路由
app.get('/api/info', (req, res) => {
  res.json({
    name: '车辆仿真系统',
    status: 'running',
    vehicleCount: simulation.getVehicleCount()
  });
});

// POI数据API
app.get('/api/poi/:category', (req, res) => {
  const category = req.params.category;
  const poiFile = path.join(__dirname, 'poi', `e_poi_${category}.csv`);
  
  // 检查文件是否存在
  if (!fs.existsSync(poiFile)) {
    return res.status(404).json({ error: 'POI文件不存在' });
  }
  
  try {
    const fileContent = fs.readFileSync(poiFile, 'utf-8');
    const lines = fileContent.split('\n').filter(line => line.trim());
    const poiData = [];
    
    // 简单CSV解析，支持引号内包含逗号的情况
    const parseCsvLine = (line) => {
      const result = [];
      let current = '';
      let inQuotes = false;
      for (let i = 0; i < line.length; i++) {
        const ch = line[i];
        if (ch === '"') {
          inQuotes = !inQuotes;
        } else if (ch === ',' && !inQuotes) {
          result.push(current.trim().replace(/^"|"$/g, ''));
          current = '';
        } else {
          current += ch;
        }
      }
      result.push(current.trim().replace(/^"|"$/g, ''));
      return result;
    };
    
    lines.forEach((line) => {
      const parts = parseCsvLine(line);
      
      if (parts.length >= 4) {
        const id = parts[0];
        const name = parts[1];
        const longitude = parseFloat(parts[2]);
        const latitude = parseFloat(parts[3]);
        
        if (!isNaN(longitude) && !isNaN(latitude) && name) {
          poiData.push({
            id: id,
            name: name,
            longitude: longitude,
            latitude: latitude,
            time: parts[4] || '',
            city: parts[5] || '',
            category: category
          });
        }
      }
    });
    
    res.json(poiData);
  } catch (error) {
    console.error('读取POI文件错误:', error);
    res.status(500).json({ error: '读取POI文件失败' });
  }
});

// 获取所有POI类别
app.get('/api/poi', (req, res) => {
  const poiDir = path.join(__dirname, 'poi');
  const categories = ['工厂', '加油站', '养车', '仓库', '维修'];
  res.json({ categories });
});

// 待接订单池（所有工厂队列中尚未被接走的订单）
app.get('/api/pending-orders', (req, res) => {
  res.json(simulation.getPendingOrdersSnapshot());
});

// Socket.IO连接处理
io.on('connection', (socket) => {
  console.log('新客户端连接:', socket.id);
  
  // 发送初始车辆数据
  socket.emit('initialVehicles', simulation.getVehicles());
  socket.emit('pendingOrdersUpdate', simulation.getPendingOrdersSnapshot());
  
  socket.on('disconnect', () => {
    console.log('客户端断开连接:', socket.id);
  });
  
  // 接收控制指令
  socket.on('controlSimulation', (data) => {
    if (data.action === 'start') {
      simulation.start();
    } else if (data.action === 'stop') {
      simulation.stop();
    } else if (data.action === 'reset') {
      simulation.reset();
    } else if (data.action === 'setTimeScale') {
      simulation.setTimeScale(data.value);
    }
  });
});

// 启动服务器
// 从.env文件读取端口，如果没有则使用3005
const PORT = process.env.PORT || 3005;
server.listen(PORT, () => {
  console.log(`服务器运行在 http://localhost:${PORT}`);
  // 启动仿真
  simulation.start();
});
