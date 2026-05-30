const Vehicle = require('../models/Vehicle');
const AMapService = require('../api/AMapService');
const fs = require('fs');
const path = require('path');

class VehicleSimulation {
  constructor(io) {
    this.io = io;
    this.vehicles = [];
    this.isRunning = false;
    this.interval = null;
    this.intervalTime = process.env.SIMULATION_INTERVAL || 1000;
    this.vehicleCount = process.env.VEHICLE_COUNT || 100;
    this.timeScale = 1; // 时间流速倍数：1=正常，2=更快
    this.orderSequence = 1;
    this.factoryOrderQueues = {}; // { [factoryId]: Order[] }
    this.factoryOrderElapsedSeconds = {}; // { [factoryId]: number }
    this.maxPendingOrdersPerFactory = 3; // 防止订单无限堆积
    this.maxOrderAgeSeconds = 20 * 60; // 订单最大寿命：20分钟（仿真时间）
    
    // POI数据
    this.poiData = {
      '工厂': [],
      '加油站': [],
      '仓库': [],
      '维修': [],
      '养车': []
    };
    
    // 加载POI数据
    this.loadPOIData();
    this.initializeFactoryOrderSystem();
    
    // 异步初始化车辆（不阻塞构造函数）
    this.initializeVehicles().catch(err => {
      console.error('初始化车辆失败:', err);
    });
  }
  
  // 加载POI数据
  loadPOIData() {
    const categories = ['工厂', '加油站', '仓库', '维修', '养车'];
    
    categories.forEach(category => {
      const poiFile = path.join(__dirname, '../../poi', `e_poi_${category}.csv`);
      
      if (fs.existsSync(poiFile)) {
        try {
          const fileContent = fs.readFileSync(poiFile, 'utf-8');
          const lines = fileContent.split('\n').filter(line => line.trim());
          
          lines.forEach(line => {
            const parts = line.split(',');
            if (parts.length >= 4) {
              const id = parts[0].trim();
              const name = parts[1].trim();
              const longitude = parseFloat(parts[2].trim());
              const latitude = parseFloat(parts[3].trim());
              
              if (!isNaN(longitude) && !isNaN(latitude) && name) {
                this.poiData[category].push({
                  id: id,
                  name: name,
                  longitude: longitude,
                  latitude: latitude,
                  category: category
                });
              }
            }
          });
          
          console.log(`已加载 ${category} POI: ${this.poiData[category].length} 个`);
        } catch (error) {
          console.error(`加载 ${category} POI 失败:`, error);
        }
      }
    });
  }

  initializeFactoryOrderSystem() {
    this.factoryOrderQueues = {};
    this.factoryOrderElapsedSeconds = {};
    const factories = this.poiData['工厂'] || [];
    factories.forEach((factory) => {
      this.factoryOrderQueues[factory.id] = [];
      this.factoryOrderElapsedSeconds[factory.id] = 0;
    });
  }
  
  // 查找最近的POI
  findNearestPOI(vehicle, poiType, excludePoiId = null) {
    const pois = this.poiData[poiType];
    if (!pois || pois.length === 0) return null;
    
    let nearest = null;
    let minDistance = Infinity;
    
    pois.forEach(poi => {
      if (excludePoiId && poi.id === excludePoiId) {
        return;
      }
      const distance = vehicle.calculateDistance(
        vehicle.longitude,
        vehicle.latitude,
        poi.longitude,
        poi.latitude
      );
      
      if (distance < minDistance) {
        minDistance = distance;
        nearest = poi;
      }
    });
    
    return nearest;
  }

  createFactoryOrder(factoryPOI) {
    const warehouses = this.poiData['仓库'] || [];
    if (warehouses.length === 0) return null;

    const warehouse = warehouses[Math.floor(Math.random() * warehouses.length)];
    const cargoValueFactor = 0.85 + Math.random() * 0.4; // 0.85x ~ 1.25x
    const deliveryDistanceM = this.calculateDistance(
      factoryPOI.longitude,
      factoryPOI.latitude,
      warehouse.longitude,
      warehouse.latitude
    );
    const deliveryDistanceKm = deliveryDistanceM / 1000;
    const baseWagePerOrder = 60;
    const wagePerKm = 12;
    const baseRevenue = baseWagePerOrder + deliveryDistanceKm * wagePerKm;
    const estimatedRevenue = baseRevenue * cargoValueFactor;

    return {
      id: `order_${this.orderSequence++}`,
      createdAt: Date.now(),
      ageSeconds: 0,
      rejectCount: 0,
      factoryId: factoryPOI.id,
      factoryName: factoryPOI.name,
      factoryLongitude: factoryPOI.longitude,
      factoryLatitude: factoryPOI.latitude,
      warehouseId: warehouse.id,
      warehouseName: warehouse.name,
      warehouseLongitude: warehouse.longitude,
      warehouseLatitude: warehouse.latitude,
      cargoValueFactor: Math.round(cargoValueFactor * 100) / 100,
      deliveryDistanceKm: Math.round(deliveryDistanceKm * 10) / 10,
      estimatedRevenue: Math.round(estimatedRevenue * 10) / 10,
      warehouse
    };
  }

  /** 供前端展示：去掉内部 warehouse 引用，保留坐标字段 */
  serializePendingOrderForClient(order) {
    if (!order) return null;
    const { warehouse: _w, ...rest } = order;
    return {
      ...rest,
      ageSeconds: Math.round((order.ageSeconds || 0) * 10) / 10
    };
  }

  /** 所有工厂队列中尚未被接走的订单（全局可见） */
  getPendingOrdersSnapshot() {
    const byFactory = {};
    const orders = [];
    Object.keys(this.factoryOrderQueues || {}).forEach((factoryId) => {
      const queue = this.factoryOrderQueues[factoryId] || [];
      byFactory[factoryId] = queue.map((o) => this.serializePendingOrderForClient(o));
      queue.forEach((o) => {
        orders.push(this.serializePendingOrderForClient(o));
      });
    });
    return {
      updatedAt: Date.now(),
      total: orders.length,
      orders,
      byFactory
    };
  }

  getFactoryOrderGenerateIntervalSeconds() {
    const factoryCount = Math.max(1, (this.poiData['工厂'] || []).length);
    const vehiclesPerFactory = Number(this.vehicleCount) / factoryCount;
    // 车辆越多，工厂出单越快；范围保持在45~180秒，避免过少或过多
    const adaptive = 120 / Math.max(0.7, vehiclesPerFactory);
    return Math.max(45, Math.min(180, adaptive));
  }

  updateFactoryOrders(dtSeconds) {
    const factories = this.poiData['工厂'] || [];
    if (factories.length === 0) return;

    const intervalSec = this.getFactoryOrderGenerateIntervalSeconds();
    factories.forEach((factory) => {
      const queue = this.factoryOrderQueues[factory.id] || [];

      // 订单老化与过期清理
      queue.forEach((order) => {
        order.ageSeconds += dtSeconds;
      });
      this.factoryOrderQueues[factory.id] = queue.filter(order => order.ageSeconds <= this.maxOrderAgeSeconds);

      this.factoryOrderElapsedSeconds[factory.id] = (this.factoryOrderElapsedSeconds[factory.id] || 0) + dtSeconds;

      // 每个工厂按节奏出单，并限制库存上限
      if (
        this.factoryOrderElapsedSeconds[factory.id] >= intervalSec &&
        this.factoryOrderQueues[factory.id].length < this.maxPendingOrdersPerFactory
      ) {
        const order = this.createFactoryOrder(factory);
        if (order) {
          this.factoryOrderQueues[factory.id].push(order);
        }
        this.factoryOrderElapsedSeconds[factory.id] = 0;
      }
    });
  }

  evaluateOrderNetProfit(vehicle, order) {
    const estimatedFuelDropPercent = order.deliveryDistanceKm * 0.1; // 与 Vehicle.updatePosition 油耗口径一致
    const estimatedFuelCost = estimatedFuelDropPercent * vehicle.fuelCostPerPercent;
    let estimatedNetProfit = order.estimatedRevenue - estimatedFuelCost;

    if (vehicle.fuel < estimatedFuelDropPercent + 5) {
      estimatedNetProfit -= 120;
    }

    return Math.round(estimatedNetProfit * 10) / 10;
  }

  /**
   * 卸货完成后：从所有工厂待接订单中选一笔预计最赚的单，
   * 从队列移除并预留，立即前往该单所属工厂。
   */
  async tryPickGlobalOrderAndRouteToFactory(vehicle) {
    if (vehicle.currentOrder || vehicle.reservedOrder) return false;
    if (!vehicle.canAcceptNewOrderAtFactory()) return false;

    const factories = this.poiData['工厂'] || [];
    let best = null;
    let bestProfit = -Infinity;

    factories.forEach((factory) => {
      const queue = this.factoryOrderQueues[factory.id] || [];
      queue.forEach((order) => {
        const p = this.evaluateOrderNetProfit(vehicle, order);
        if (p >= 0 && p > bestProfit) {
          bestProfit = p;
          best = { order, factory };
        }
      });
    });

    if (!best) return false;

    const q = this.factoryOrderQueues[best.order.factoryId];
    const idx = (q || []).findIndex((o) => o.id === best.order.id);
    if (idx === -1) return false;
    q.splice(idx, 1);

    const { order, factory } = best;
    vehicle.reservedOrder = {
      id: order.id,
      factoryId: order.factoryId,
      factoryName: order.factoryName,
      warehouseId: order.warehouseId,
      warehouseName: order.warehouseName,
      cargoValueFactor: order.cargoValueFactor,
      deliveryDistanceKm: order.deliveryDistanceKm,
      estimatedRevenue: order.estimatedRevenue
    };
    vehicle.currentTask = 'going_to_factory';
    vehicle.targetPOI = factory;
    await this.generateRouteToPOI(vehicle, factory);
    return true;
  }

  // 工厂到达后的订单决策逻辑
  async handleFactoryOrderDecision(vehicle, factoryPOI) {
    // 走错厂：继续导航去预留单对应工厂
    if (vehicle.reservedOrder && vehicle.reservedOrder.factoryId !== factoryPOI.id) {
      const factories = this.poiData['工厂'] || [];
      const correctFactory = factories.find((x) => x.id === vehicle.reservedOrder.factoryId);
      if (correctFactory) {
        vehicle.currentTask = 'going_to_factory';
        vehicle.targetPOI = correctFactory;
        await this.generateRouteToPOI(vehicle, correctFactory);
      }
      return;
    }

    // 已预留订单：到对应工厂后直接装货并开始派送
    if (vehicle.reservedOrder && vehicle.reservedOrder.factoryId === factoryPOI.id) {
      const ro = vehicle.reservedOrder;
      const warehouses = this.poiData['仓库'] || [];
      const targetWarehouse = warehouses.find((w) => w.id === ro.warehouseId);
      if (targetWarehouse) {
        const estimatedNetProfit = this.evaluateOrderNetProfit(vehicle, {
          deliveryDistanceKm: ro.deliveryDistanceKm,
          estimatedRevenue: ro.estimatedRevenue
        });
        vehicle.reservedOrder = null;
        vehicle.hasCargo = true;
        vehicle.cargoMileage = 0;
        vehicle.cargoValueFactor = ro.cargoValueFactor;
        vehicle.currentOrder = {
          id: ro.id,
          factoryId: ro.factoryId,
          factoryName: ro.factoryName,
          warehouseId: ro.warehouseId,
          warehouseName: ro.warehouseName,
          cargoValueFactor: ro.cargoValueFactor,
          deliveryDistanceKm: ro.deliveryDistanceKm,
          estimatedRevenue: ro.estimatedRevenue,
          estimatedNetProfit: estimatedNetProfit
        };
        vehicle.currentTask = 'going_to_warehouse';
        await this.generateRouteToPOI(vehicle, targetWarehouse);
        return;
      }
      vehicle.reservedOrder = null;
    }

    // 规则：当前订单未完成时，不能接下一单，必须继续送原订单
    if (vehicle.currentOrder && vehicle.currentOrder.warehouseId) {
      const warehouses = this.poiData['仓库'] || [];
      const targetWarehouse = warehouses.find(w => w.id === vehicle.currentOrder.warehouseId);
      if (targetWarehouse) {
        vehicle.hasCargo = true;
        vehicle.currentTask = 'going_to_warehouse';
        vehicle.targetPOI = targetWarehouse;
        await this.generateRouteToPOI(vehicle, targetWarehouse);
        return;
      }
    }

    const queue = this.factoryOrderQueues[factoryPOI.id] || [];
    if (queue.length === 0) {
      // 当前工厂暂无订单，去下一个工厂
      vehicle.hasCargo = false;
      vehicle.currentTask = 'going_to_factory';
      const nextFactory = this.findNearestPOI(vehicle, '工厂', factoryPOI.id);
      if (nextFactory) {
        vehicle.targetPOI = nextFactory;
        await this.generateRouteToPOI(vehicle, nextFactory);
      }
      return;
    }

    // 订单由工厂定时生成；司机只对队首订单做接单判断
    const generatedOrder = queue[0];
    const estimatedNetProfit = this.evaluateOrderNetProfit(vehicle, generatedOrder);

    // 只有预计不亏且允许接新单时才接单（派送中或有未完成订单时不接）
    if (estimatedNetProfit >= 0 && vehicle.canAcceptNewOrderAtFactory()) {
      vehicle.hasCargo = true;
      vehicle.currentTask = 'going_to_warehouse';
      vehicle.targetPOI = generatedOrder.warehouse;
      vehicle.cargoValueFactor = generatedOrder.cargoValueFactor;
      vehicle.currentOrder = {
        id: generatedOrder.id,
        factoryId: generatedOrder.factoryId,
        factoryName: generatedOrder.factoryName,
        warehouseId: generatedOrder.warehouseId,
        warehouseName: generatedOrder.warehouseName,
        cargoValueFactor: generatedOrder.cargoValueFactor,
        deliveryDistanceKm: generatedOrder.deliveryDistanceKm,
        estimatedRevenue: generatedOrder.estimatedRevenue,
        estimatedNetProfit: estimatedNetProfit
      };
      queue.shift(); // 接单后从工厂订单池移除
      await this.generateRouteToPOI(vehicle, generatedOrder.warehouse);
      return;
    }

    // 不盈利则不接单：订单留在池中并轮转，司机去下一个工厂
    generatedOrder.rejectCount = (generatedOrder.rejectCount || 0) + 1;
    if (queue.length > 1) {
      queue.push(queue.shift());
    }
    vehicle.hasCargo = false;
    vehicle.currentOrder = null;
    vehicle.cargoValueFactor = 1;
    vehicle.currentTask = 'going_to_factory';
    const nextFactory = this.findNearestPOI(vehicle, '工厂', factoryPOI.id);
    if (nextFactory) {
      vehicle.targetPOI = nextFactory;
      await this.generateRouteToPOI(vehicle, nextFactory);
    }
  }
  
  async initializeVehicles() {
    // 创建初始车辆（所有车辆都是货车）
    for (let i = 0; i < this.vehicleCount; i++) {
      const vehicle = new Vehicle({
        id: `vehicle_${i + 1}`,
        type: 'truck',
        // 北京区域的随机初始位置
        latitude: 39.8 + Math.random() * 0.4,
        longitude: 116.3 + Math.random() * 0.4,
        speed: 20 + Math.random() * 30, // 20-50 km/h
        direction: Math.random() * 360
      });
      
      // 初始任务：去工厂拿货
      await this.assignTaskToVehicle(vehicle);
      
      this.vehicles.push(vehicle);
    }
  }
  
  // 为车辆分配任务
  async assignTaskToVehicle(vehicle) {
    // 检查是否需要紧急任务
    const urgentTask = vehicle.needsUrgentTask();
    
    if (urgentTask) {
      // 处理紧急任务
      switch(urgentTask.type) {
        case 'refueling':
          const gasStation = this.findNearestPOI(vehicle, '加油站');
          if (gasStation) {
            vehicle.currentTask = 'refueling';
            vehicle.targetPOI = gasStation;
            await this.generateRouteToPOI(vehicle, gasStation);
            return;
          }
          break;
        case 'repairing':
          const repairShop = this.findNearestPOI(vehicle, '维修');
          if (repairShop) {
            vehicle.currentTask = 'repairing';
            vehicle.targetPOI = repairShop;
            await this.generateRouteToPOI(vehicle, repairShop);
            return;
          }
          break;
        case 'washing':
          const washShop = this.findNearestPOI(vehicle, '养车');
          if (washShop) {
            vehicle.currentTask = 'washing';
            vehicle.targetPOI = washShop;
            await this.generateRouteToPOI(vehicle, washShop);
            return;
          }
          break;
      }
    }

    // 维修/加油等紧急任务完成后，若存在未完成订单，优先继续原订单（前往该订单仓库）
    if (vehicle.currentOrder && vehicle.currentOrder.warehouseId) {
      const warehouses = this.poiData['仓库'] || [];
      const targetWarehouse = warehouses.find(w => w.id === vehicle.currentOrder.warehouseId);
      if (targetWarehouse) {
        vehicle.hasCargo = true;
        vehicle.currentTask = 'going_to_warehouse';
        vehicle.targetPOI = targetWarehouse;
        await this.generateRouteToPOI(vehicle, targetWarehouse);
        return;
      }
    }

    // 已全局选单、正前往工厂装货途中（中断后恢复导航）
    if (vehicle.reservedOrder && vehicle.reservedOrder.factoryId) {
      const factories = this.poiData['工厂'] || [];
      const f = factories.find((x) => x.id === vehicle.reservedOrder.factoryId);
      if (f) {
        vehicle.currentTask = 'going_to_factory';
        vehicle.targetPOI = f;
        await this.generateRouteToPOI(vehicle, f);
        return;
      }
      vehicle.reservedOrder = null;
    }

    // 无在送单：立刻从全局待接订单中选一单并前往对应工厂
    if (!vehicle.currentOrder && !vehicle.reservedOrder) {
      const picked = await this.tryPickGlobalOrderAndRouteToFactory(vehicle);
      if (picked) return;
    }
    
    // 正常任务流程
    if (vehicle.currentTask === 'going_to_factory') {
      // 去工厂拿货
      const factory = this.findNearestPOI(vehicle, '工厂');
      if (factory) {
        vehicle.targetPOI = factory;
        await this.generateRouteToPOI(vehicle, factory);
      }
    } else if (vehicle.currentTask === 'going_to_warehouse') {
      // 有在途订单时按订单指定仓库；否则回退到最近仓库
      if (vehicle.currentOrder && vehicle.currentOrder.warehouseId) {
        const warehouses = this.poiData['仓库'] || [];
        const targetWarehouse = warehouses.find(w => w.id === vehicle.currentOrder.warehouseId);
        if (targetWarehouse) {
          vehicle.targetPOI = targetWarehouse;
          await this.generateRouteToPOI(vehicle, targetWarehouse);
          return;
        }
      }
      const warehouse = this.findNearestPOI(vehicle, '仓库');
      if (warehouse) {
        vehicle.targetPOI = warehouse;
        await this.generateRouteToPOI(vehicle, warehouse);
      }
    } else {
      // 默认去工厂
      vehicle.currentTask = 'going_to_factory';
      const factory = this.findNearestPOI(vehicle, '工厂');
      if (factory) {
        vehicle.targetPOI = factory;
        await this.generateRouteToPOI(vehicle, factory);
      }
    }
  }
  
  // 生成到POI的路线
  async generateRouteToPOI(vehicle, poi) {
    const startPoint = `${vehicle.longitude},${vehicle.latitude}`;
    const endPoint = `${poi.longitude},${poi.latitude}`;
    
    try {
      const route = await AMapService.getDrivingRoute(startPoint, endPoint);
      if (route && route.paths && route.paths.length > 0) {
        vehicle.setRoute(route.paths[0]);
      }
    } catch (error) {
      console.error(`为车辆${vehicle.id}生成到${poi.name}的路线失败:`, error);
      vehicle.destination = {
        longitude: poi.longitude,
        latitude: poi.latitude
      };
    }
  }
  
  setTimeScale(scale) {
    const n = Number(scale);
    if (!Number.isFinite(n)) return;
    // 限制取值避免极端导致数值爆炸/性能问题
    this.timeScale = Math.max(0.1, Math.min(20, n));
  }

  
  start() {
    if (this.isRunning) return;
    
    this.isRunning = true;
    this.interval = setInterval(async () => {
      await this.updateVehicles();
      this.broadcastVehicles();
    }, this.intervalTime);
    
    console.log('车辆仿真已启动');
  }
  
  stop() {
    if (!this.isRunning) return;
    
    clearInterval(this.interval);
    this.isRunning = false;
    console.log('车辆仿真已停止');
  }
  
  async reset() {
    this.stop();
    this.vehicles = [];
    this.initializeFactoryOrderSystem();
    await this.initializeVehicles();
    this.start();
    console.log('车辆仿真已重置');
  }
  
  async updateVehicles() {
    const baseDtSeconds = this.intervalTime / 1000;
    const dtSeconds = baseDtSeconds * this.timeScale;
    this.updateFactoryOrders(dtSeconds);

    for (const vehicle of this.vehicles) {
      vehicle.updatePosition(dtSeconds);
      
      // 检查是否到达目的地
      if (vehicle.hasReachedDestination()) {
        // 到达POI时的处理
        if (vehicle.targetPOI) {
          const arrivedPOI = vehicle.targetPOI;
          vehicle.arriveAtPOI(arrivedPOI.category);
          vehicle.targetPOI = null;

          // 到工厂后：先随机生成订单，再由司机按预计盈亏决定是否接单
          if (arrivedPOI.category === '工厂') {
            await this.handleFactoryOrderDecision(vehicle, arrivedPOI);
            continue;
          }
        }
        
        // 重新分配任务
        await this.assignTaskToVehicle(vehicle);
      }
    }
  }
  
  broadcastVehicles() {
    const vehicleData = this.vehicles.map(v => v.toJSON());
    this.io.emit('vehicleUpdate', vehicleData);
    this.io.emit('pendingOrdersUpdate', this.getPendingOrdersSnapshot());
  }
  
  getVehicles() {
    return this.vehicles.map(v => v.toJSON());
  }
  
  getVehicleCount() {
    return this.vehicles.length;
  }

  calculateDistance(lon1, lat1, lon2, lat2) {
    const R = 6371000;
    const φ1 = (lat1 * Math.PI) / 180;
    const φ2 = (lat2 * Math.PI) / 180;
    const Δφ = ((lat2 - lat1) * Math.PI) / 180;
    const Δλ = ((lon2 - lon1) * Math.PI) / 180;
    const a =
      Math.sin(Δφ / 2) * Math.sin(Δφ / 2) +
      Math.cos(φ1) * Math.cos(φ2) *
      Math.sin(Δλ / 2) * Math.sin(Δλ / 2);
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    return R * c;
  }
}

module.exports = VehicleSimulation;
