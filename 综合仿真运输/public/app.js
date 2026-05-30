// 全局变量
let map = null;
let socket = null;
let vehicleMarkers = {};
let vehicleHistory = {};
let activeVehicleId = null;
let poiMarkers = {}; // POI标记
let poiCategoryLoaded = {}; // POI类别是否已加载
let poiSelectedCategories = new Set(); // 当前勾选要显示的POI类别

// 初始化函数
async function init() {
  // 初始化地图
  initMap();
  
  // 初始化Socket.IO连接
  initSocket();

  // 先拉一次待接订单（Socket 连接后也会推送，双保险）
  try {
    const res = await fetch('/api/pending-orders');
    if (res.ok) {
      updatePendingOrdersUI(await res.json());
    }
  } catch (e) {
    // 忽略
  }
  
  // 绑定控制按钮事件
  bindEvents();
  
  // 初始化POI筛选面板 & 加载POI数据
  await initPOIFilter();
}

// 初始化高德地图
function initMap() {
  // 创建地图实例
  map = new AMap.Map('mapContainer', {
    zoom: 12,
    center: [116.404, 39.915], // 北京中心点
    viewMode: '3D',
    showBuildingBlock: true,
    buildingsAnimation: true
  });
  
  // 添加控件
  AMap.plugin([
    'AMap.ToolBar',
    'AMap.Scale',
    'AMap.HawkEye',
    'AMap.MapType',
    'AMap.Geolocation'
  ], function() {
    map.addControl(new AMap.ToolBar({
      position: 'RB'
    }));
    
    map.addControl(new AMap.Scale({
      position: 'RB'
    }));
    
    map.addControl(new AMap.MapType({
      defaultType: 0,
      showTraffic: true
    }));
    
    map.addControl(new AMap.Geolocation({
      enableHighAccuracy: true,
      timeout: 10000,
      buttonPosition: 'LB',
      buttonOffset: new AMap.Pixel(10, 20)
    }));
  });
  
  // 添加比例尺
  map.plugin('AMap.Scale', function() {
    const scale = new AMap.Scale();
    map.addControl(scale);
  });
}

// 初始化Socket.IO连接
function initSocket() {
  socket = io();
  
  // 连接成功
  socket.on('connect', function() {
    console.log('已连接到服务器');
  });
  
  // 接收初始车辆数据
  socket.on('initialVehicles', function(vehicles) {
    updateVehicleList(vehicles);
    updateVehicleCount(vehicles.length);
  });
  
  // 接收车辆更新数据
  socket.on('vehicleUpdate', function(vehicles) {
    updateVehiclesOnMap(vehicles);
    updateRealTimeData(vehicles);
    updateVehicleList(vehicles);
  });

  // 全局待接订单池（各工厂队列中尚未被接走的订单）
  socket.on('pendingOrdersUpdate', function(snapshot) {
    updatePendingOrdersUI(snapshot);
  });
  
  // 连接断开
  socket.on('disconnect', function() {
    console.log('与服务器断开连接');
  });
  
  // 连接错误
  socket.on('error', function(error) {
    console.error('Socket连接错误:', error);
  });
}

// 绑定事件
function bindEvents() {
  // 控制按钮事件
  document.getElementById('startBtn').addEventListener('click', function() {
    socket.emit('controlSimulation', { action: 'start' });
  });
  
  document.getElementById('stopBtn').addEventListener('click', function() {
    socket.emit('controlSimulation', { action: 'stop' });
  });
  
  document.getElementById('resetBtn').addEventListener('click', function() {
    // 清除现有标记
    clearAllMarkers();
    vehicleHistory = {};
    
    // 发送重置命令
    socket.emit('controlSimulation', { action: 'reset' });
  });

  // 时间流速
  const timeScaleSelect = document.getElementById('timeScaleSelect');
  if (timeScaleSelect) {
    // 初始同步一次（避免后端默认值与前端选择不一致）
    socket.emit('controlSimulation', { action: 'setTimeScale', value: timeScaleSelect.value });
    
    timeScaleSelect.addEventListener('change', function() {
      socket.emit('controlSimulation', { action: 'setTimeScale', value: timeScaleSelect.value });
    });
  }
}

// 更新地图上的车辆
function updateVehiclesOnMap(vehicles) {
  vehicles.forEach(vehicle => {
    const position = [vehicle.longitude, vehicle.latitude];
    
    // 初始化历史记录
    if (!vehicleHistory[vehicle.id]) {
      vehicleHistory[vehicle.id] = [];
    }
    
    // 添加到历史记录
    vehicleHistory[vehicle.id].push(position);
    
    // 限制历史记录长度
    if (vehicleHistory[vehicle.id].length > 100) {
      vehicleHistory[vehicle.id].shift();
    }
    
    // 获取或创建标记
    let marker = vehicleMarkers[vehicle.id];
    if (!marker) {
      // 创建新标记
      marker = createVehicleMarker(vehicle);
      vehicleMarkers[vehicle.id] = marker;
    } else {
      // 更新标记位置
      marker.setPosition(position);
      
      // 更新车辆信息
      marker.setTitle(`ID: ${vehicle.id}\n类型: ${getVehicleTypeName(vehicle.type)}\n速度: ${vehicle.speed.toFixed(1)} km/h`);
    }
    
    // 如果是当前选中的车辆，显示轨迹
    if (activeVehicleId === vehicle.id) {
      showVehicleTrail(vehicle.id);
    }
  });
}

/** 车辆图标（统一用本地资源，避免选中时外链图标加载失败导致标记空白） */
function createTruckIcon(sizePx) {
  const s = sizePx;
  return new AMap.Icon({
    size: new AMap.Size(s, s),
    image: '/icons/truck.png',
    imageSize: new AMap.Size(s, s)
  });
}

// 创建车辆标记
function createVehicleMarker(vehicle) {
  const position = [vehicle.longitude, vehicle.latitude];
  
  // 所有车辆都是货车
  const icon = createTruckIcon(32);
  
  // 创建标记
  // 保持图标方向不变（不旋转）
  const markerAngle = 0;
  const marker = new AMap.Marker({
    position: position,
    icon: icon,
    angle: markerAngle,
    title: `ID: ${vehicle.id}\n类型: ${getVehicleTypeName(vehicle.type)}\n速度: ${vehicle.speed.toFixed(1)} km/h`,
    animation: 'AMAP_ANIMATION_DROP'
  });
  
  // 添加点击事件
  marker.on('click', function() {
    selectVehicle(vehicle.id);
  });
  
  // 添加到地图
  marker.setMap(map);
  
  return marker;
}

// 选择车辆
function selectVehicle(vehicleId) {
  // 取消之前选中的车辆样式
  if (activeVehicleId && vehicleMarkers[activeVehicleId]) {
    const oldMarker = vehicleMarkers[activeVehicleId];
    // 恢复为默认尺寸（不依赖 getVehicleById，避免偶发无法还原图标）
    oldMarker.setIcon(createTruckIcon(32));
    
    // 移除之前的轨迹
    removeVehicleTrail();
  }
  
  // 设置新选中的车辆
  activeVehicleId = vehicleId;
  
  // 更新选中车辆的样式
  if (vehicleMarkers[vehicleId]) {
    const marker = vehicleMarkers[vehicleId];
    // 高亮：仍用同一本地图标，略放大即可（避免外链 yellow01.png 加载失败）
    marker.setIcon(createTruckIcon(38));
    
    // 显示轨迹
    showVehicleTrail(vehicleId);
    
    // 缩放到车辆位置
    map.setCenter(marker.getPosition());
    map.setZoom(15);
  }
  
  // 更新车辆列表高亮
  updateVehicleListHighlight(vehicleId);
}

// 显示车辆轨迹
function showVehicleTrail(vehicleId) {
  // 移除之前的轨迹
  removeVehicleTrail();
  
  const history = vehicleHistory[vehicleId];
  if (!history || history.length < 2) return;
  
  // 创建轨迹线
  const polyline = new AMap.Polyline({
    path: history,
    strokeColor: '#1890ff',
    strokeWeight: 3,
    strokeOpacity: 0.6,
    lineJoin: 'round',
    lineCap: 'round',
    zIndex: 10
  });
  
  // 保存轨迹线引用
  window.activeTrail = polyline;
  
  // 添加到地图
  polyline.setMap(map);
}

// 移除车辆轨迹
function removeVehicleTrail() {
  if (window.activeTrail) {
    window.activeTrail.setMap(null);
    window.activeTrail = null;
  }
}

// 更新侧边栏「待接订单池」（与车辆位置无关，展示所有工厂队列中未接订单）
function updatePendingOrdersUI(snapshot) {
  const listEl = document.getElementById('pendingOrdersList');
  const countEl = document.getElementById('pendingOrdersCount');
  if (!listEl || !countEl) return;

  const orders = (snapshot && Array.isArray(snapshot.orders)) ? snapshot.orders : [];
  countEl.textContent = `(${orders.length})`;

  if (orders.length === 0) {
    listEl.innerHTML = '\u003cp\u003e当前没有待接订单\u003c/p\u003e';
    return;
  }

  listEl.innerHTML = '';
  orders.forEach((o) => {
    const div = document.createElement('div');
    div.className = 'pending-order-item';
    const factor = o.cargoValueFactor != null ? o.cargoValueFactor.toFixed(2) : '-';
    const dist = o.deliveryDistanceKm != null ? o.deliveryDistanceKm.toFixed(1) : '-';
    const rev = o.estimatedRevenue != null ? o.estimatedRevenue.toFixed(1) : '-';
    const age = o.ageSeconds != null ? o.ageSeconds.toFixed(0) : '0';
    const rejects = o.rejectCount != null ? o.rejectCount : 0;
    div.innerHTML = `
      \u003cdiv class="order-id"\u003e${o.id}\u003c/div\u003e
      \u003cdiv\u003e${o.factoryName || o.factoryId} → ${o.warehouseName || o.warehouseId}\u003c/div\u003e
      \u003cdiv\u003e里程约: ${dist} km | 预估收入: ${rev} 元 | 贵重系数: ${factor}\u003c/div\u003e
      \u003cdiv\u003e已等待: ${age}s | 被拒次数: ${rejects}\u003c/div\u003e
    `;
    listEl.appendChild(div);
  });
}

// 更新车辆列表
function updateVehicleList(vehicles) {
  const container = document.getElementById('vehicleList');
  container.innerHTML = '';
  
  if (vehicles.length === 0) {
    container.innerHTML = '\u003cp\u003e暂无车辆数据\u003c/p\u003e';
    return;
  }
  
  vehicles.forEach(vehicle => {
    const item = document.createElement('div');
    item.className = `vehicle-item ${activeVehicleId === vehicle.id ? 'active' : ''}`;
    item.dataset.id = vehicle.id;
    
    const updateTime = new Date(vehicle.lastUpdated).toLocaleTimeString();
    
    // 获取目的地信息
    let destinationText = '无';
    if (vehicle.targetPOI) {
      destinationText = `${vehicle.targetPOI.name} (${vehicle.targetPOI.category})`;
    } else if (vehicle.currentTask) {
      destinationText = getTaskName(vehicle.currentTask);
    }
    
    // 获取油量和健康值（如果存在）
    const fuelText = vehicle.fuel !== undefined ? `${vehicle.fuel.toFixed(1)}%` : '未知';
    const healthText = vehicle.health !== undefined ? `${vehicle.health.toFixed(1)}%` : '未知';
    const profitValue = vehicle.profit !== undefined ? vehicle.profit : 0;
    const profitPrefix = profitValue >= 0 ? '+' : '';
    const profitColor = profitValue >= 0 ? '#52c41a' : '#ff4d4f';
    const ordersText = vehicle.ordersCompleted !== undefined ? vehicle.ordersCompleted : 0;
    const canAccept =
      vehicle.canAcceptNewOrder != null
        ? vehicle.canAcceptNewOrder
        : !vehicle.currentOrder &&
          !vehicle.reservedOrder &&
          !(vehicle.hasCargo && vehicle.currentTask === 'going_to_warehouse');
    const acceptText = canAccept ? '可接' : '不可接';
    const acceptColor = canAccept ? '#52c41a' : '#8c8c8c';
    const delivering =
      vehicle.hasDeliveryInProgress != null
        ? vehicle.hasDeliveryInProgress
        : !!(vehicle.currentOrder && vehicle.hasCargo && vehicle.currentTask === 'going_to_warehouse');
    const deliveryText = delivering ? '是' : '否';
    const deliveryColor = delivering ? '#1890ff' : '#8c8c8c';
    const reservedText = vehicle.reservedOrder && vehicle.reservedOrder.id
      ? `${vehicle.reservedOrder.id} → ${vehicle.reservedOrder.factoryName || ''}`
      : '无';
    
    item.innerHTML = `
      \u003ch4\u003e${vehicle.id} \u003cspan class="vehicle-type ${vehicle.type}"\u003e${getVehicleTypeName(vehicle.type)}\u003c/span\u003e\u003c/h4\u003e
      \u003cdiv class="vehicle-details"\u003e
        \u003cdiv\u003e可接新单: \u003cspan style="color:${acceptColor};font-weight:500;"\u003e${acceptText}\u003c/span\u003e\u003c/div\u003e
        \u003cdiv\u003e派送中: \u003cspan style="color:${deliveryColor};font-weight:500;"\u003e${deliveryText}\u003c/span\u003e\u003c/div\u003e
        \u003cdiv\u003e预选订单(前往工厂): ${reservedText}\u003c/div\u003e
        \u003cdiv\u003e位置: ${vehicle.longitude.toFixed(6)}, ${vehicle.latitude.toFixed(6)}\u003c/div\u003e
        \u003cdiv\u003e速度: ${vehicle.speed.toFixed(1)} km/h\u003c/div\u003e
        \u003cdiv\u003e方向: ${vehicle.direction.toFixed(0)}°\u003c/div\u003e
        \u003cdiv\u003e状态: ${getStatusText(vehicle.status)}\u003c/div\u003e
        \u003cdiv\u003e油量: ${fuelText}\u003c/div\u003e
        \u003cdiv\u003e健康值: ${healthText}\u003c/div\u003e
        \u003cdiv\u003e完成单数: ${ordersText}\u003c/div\u003e
        \u003cdiv\u003e盈亏: \u003cspan style="color:${profitColor};font-weight:600;"\u003e${profitPrefix}${profitValue.toFixed(1)} 元\u003c/span\u003e\u003c/div\u003e
        \u003cdiv\u003e目的地: ${destinationText}\u003c/div\u003e
        \u003cdiv\u003e更新时间: ${updateTime}\u003c/div\u003e
      \u003c/div\u003e
    `;
    
    // 添加点击事件
    item.addEventListener('click', function() {
      selectVehicle(vehicle.id);
    });
    
    container.appendChild(item);
  });
}

// 更新车辆列表高亮
function updateVehicleListHighlight(vehicleId) {
  const items = document.querySelectorAll('.vehicle-item');
  items.forEach(item => {
    if (item.dataset.id === vehicleId) {
      item.classList.add('active');
    } else {
      item.classList.remove('active');
    }
  });
}

// 更新实时数据显示
function updateRealTimeData(vehicles) {
  const container = document.getElementById('realTimeData');
  
  if (vehicles.length === 0) {
    container.innerHTML = '\u003cp\u003e暂无数据\u003c/p\u003e';
    return;
  }
  
  // 统计数据
  const stats = {
    total: vehicles.length,
    avgSpeed: vehicles.reduce((sum, v) => sum + v.speed, 0) / vehicles.length
  };
  
  const now = new Date().toLocaleString();
  
  container.innerHTML = `
    \u003cdiv class="real-time-item"\u003e
      \u003cspan class="label"\u003e更新时间:\u003c/span\u003e
      \u003cspan class="value"\u003e${now}\u003c/span\u003e
    \u003c/div\u003e
    \u003cdiv class="real-time-item"\u003e
      \u003cspan class="label"\u003e总车辆数:\u003c/span\u003e
      \u003cspan class="value"\u003e${stats.total}\u003c/span\u003e
    \u003c/div\u003e
    \u003cdiv class="real-time-item"\u003e
      \u003cspan class="label"\u003e平均速度:\u003c/span\u003e
      \u003cspan class="value"\u003e${stats.avgSpeed.toFixed(1)} km/h\u003c/span\u003e
    \u003c/div\u003e
  `;
}

// 更新车辆数量显示
function updateVehicleCount(count) {
  document.getElementById('vehicleCount').textContent = `车辆数量: ${count}`;
}

// 清除所有标记
function clearAllMarkers() {
  Object.values(vehicleMarkers).forEach(marker => {
    marker.setMap(null);
  });
  vehicleMarkers = {};
}

// 工具函数
function getVehicleTypeName(type) {
  return '货车';
}

function getStatusText(status) {
  const statusTexts = {
    'running': '运行中',
    'stopped': '已停止',
    'waiting': '等待中',
    'error': '错误'
  };
  return statusTexts[status] || '未知';
}

function getTaskName(task) {
  const taskNames = {
    'going_to_factory': '前往工厂',
    'going_to_warehouse': '前往仓库',
    'refueling': '前往加油站',
    'repairing': '前往维修店',
    'washing': '前往洗车店'
  };
  return taskNames[task] || '未知任务';
}

function getVehicleById(id) {
  // 这里应该从最近更新的数据中查找，但为了简化，我们直接返回标记的信息
  const marker = vehicleMarkers[id];
  if (!marker) return null;
  
  const position = marker.getPosition();
  return {
    id: id,
    longitude: position[0],
    latitude: position[1],
    // 其他属性可能需要从其他地方获取
    type: 'unknown'
  };
}

// 加载POI数据
async function loadPOIData() {
  // 兼容旧调用：默认加载已选择的
  return loadPOIDataByCategories(Array.from(poiSelectedCategories));
}

function getPOICategoryIcons() {
  return {
    '工厂': '/icons/factory.png',
    '加油站': '/icons/gas.png',
    '养车': '/icons/wash.png',
    '仓库': '/icons/garbage.png',
    '维修': '/icons/fix.png'
  };
}

async function fetchPOICategories() {
  try {
    const response = await fetch('/api/poi');
    const data = await response.json();
    if (data && Array.isArray(data.categories) && data.categories.length > 0) {
      return data.categories;
    }
  } catch (e) {
    // 忽略，走默认
  }
  return ['工厂', '加油站', '养车', '仓库', '维修'];
}

function setPOICategoryVisible(category, visible) {
  const markers = poiMarkers[category] || [];
  markers.forEach((marker) => {
    marker.setMap(visible ? map : null);
  });
}

async function ensurePOICategoryLoaded(category) {
  if (poiCategoryLoaded[category]) return;
  await loadPOIDataByCategories([category]);
  poiCategoryLoaded[category] = true;
}

async function loadPOIDataByCategories(categories) {
  const categoryIcons = getPOICategoryIcons();

  for (const category of categories) {
    try {
      if (poiCategoryLoaded[category]) {
        // 已加载过：只需要根据勾选状态显示/隐藏
        setPOICategoryVisible(category, poiSelectedCategories.has(category));
        continue;
      }

      const response = await fetch(`/api/poi/${category}`);
      const poiData = await response.json();
      
      // 在地图上显示POI点
      poiData.forEach(poi => {
        const position = [poi.longitude, poi.latitude];
        const iconUrl = categoryIcons[category] || 'https://webapi.amap.com/theme/v1.3/markers/n/mark_b.png';
        
        const icon = new AMap.Icon({
          size: new AMap.Size(32, 32),
          image: iconUrl,
          imageSize: new AMap.Size(32, 32)
        });
        
        const marker = new AMap.Marker({
          position: position,
          icon: icon,
          title: `${poi.name}\n类别: ${category}`,
          zIndex: 1 // POI点层级低于车辆
        });
        
        // 添加到地图
        marker.setMap(poiSelectedCategories.has(category) ? map : null);
        
        // 保存标记引用
        if (!poiMarkers[category]) {
          poiMarkers[category] = [];
        }
        poiMarkers[category].push(marker);
      });
      
      console.log(`已加载 ${category} POI: ${poiData.length} 个`);
      poiCategoryLoaded[category] = true;
    } catch (error) {
      console.error(`加载 ${category} POI 失败:`, error);
    }
  }
}

async function initPOIFilter() {
  const categories = await fetchPOICategories();
  const icons = getPOICategoryIcons();

  // 默认全选
  poiSelectedCategories = new Set(categories);

  const listEl = document.getElementById('poiFilterList');
  const selectAllBtn = document.getElementById('poiSelectAllBtn');
  const clearAllBtn = document.getElementById('poiClearAllBtn');

  if (!listEl || !selectAllBtn || !clearAllBtn) {
    // UI不存在则仍然按旧逻辑加载全部
    await loadPOIDataByCategories(categories);
    return;
  }

  // 渲染复选框列表
  listEl.innerHTML = '';
  categories.forEach((category) => {
    const id = `poi_cb_${encodeURIComponent(category)}`;
    const item = document.createElement('label');
    item.className = 'poi-filter-item';
    item.setAttribute('for', id);

    const iconUrl = icons[category];
    const iconHtml = iconUrl ? `<img class="poi-filter-icon" src="${iconUrl}" alt="${category}">` : '';

    item.innerHTML = `
      <input id="${id}" type="checkbox" checked />
      ${iconHtml}
      <span>${category}</span>
    `;

    const checkbox = item.querySelector('input[type="checkbox"]');
    checkbox.addEventListener('change', async () => {
      const checked = checkbox.checked;
      if (checked) {
        poiSelectedCategories.add(category);
        await ensurePOICategoryLoaded(category);
        setPOICategoryVisible(category, true);
      } else {
        poiSelectedCategories.delete(category);
        setPOICategoryVisible(category, false);
      }
    });

    listEl.appendChild(item);
  });

  selectAllBtn.addEventListener('click', async () => {
    const checkboxes = listEl.querySelectorAll('input[type="checkbox"]');
    categories.forEach((c) => poiSelectedCategories.add(c));
    checkboxes.forEach((cb) => { cb.checked = true; });
    await loadPOIDataByCategories(categories);
    categories.forEach((c) => setPOICategoryVisible(c, true));
  });

  clearAllBtn.addEventListener('click', () => {
    const checkboxes = listEl.querySelectorAll('input[type="checkbox"]');
    poiSelectedCategories.clear();
    checkboxes.forEach((cb) => { cb.checked = false; });
    categories.forEach((c) => setPOICategoryVisible(c, false));
  });

  // 初次加载：加载全部类别（保持后续切换不卡）
  await loadPOIDataByCategories(categories);
}

// 页面加载完成后初始化
window.addEventListener('load', init);
