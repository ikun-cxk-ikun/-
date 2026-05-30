class Vehicle {
  constructor({
    id,
    type = 'car',
    latitude,
    longitude,
    speed = 30,
    direction = 0,
    status = 'running'
  }) {
    this.id = id;
    this.type = type;
    this.latitude = latitude;
    this.longitude = longitude;
    this.speed = speed; // km/h
    this.direction = direction; // 角度
    this.status = status;
    this.route = null;
    this.currentStep = 0;
    this.destination = null;
    this.history = [];
    this.lastUpdated = Date.now();
    
    // 新增状态属性
    this.hasCargo = false; // 是否载货
    this.fuel = 100; // 油量百分比 (0-100)
    this.health = 100; // 健康度百分比 (0-100)
    this.isBroken = false; // 是否处于故障状态（故障触发维修）
    this.totalMileage = 0; // 总里程（米）
    this.mileageSinceWash = 0; // 上次洗车后的里程（米）
    this.currentTask = 'going_to_factory'; // 当前任务: going_to_factory, going_to_warehouse, refueling, repairing, washing
    this.targetPOI = null; // 目标POI信息 {type, id, longitude, latitude, name}

    
    // 盈亏相关字段（单位：元）
    this.profit = 0;
    this.ordersCompleted = 0;
    this.cargoMileage = 0; // 本单载货里程（米）
    this.cargoValueFactor = 1; // 本单货物贵重系数
    this.currentOrder = null; // 当前订单信息
    /** 全局选单后、尚未到厂装货前预留的订单（已从工厂队列移除） */
    this.reservedOrder = null;
    this.lastFuel = this.fuel;
    this.lastHealth = this.health;

    // 成本/收益参数（可按业务调参）
    this.fuelCostPerPercent = 8; // 每消耗1%油量扣费
    this.baseWagePerOrder = 60; // 每单基础工资
    this.wagePerKm = 12; // 每公里额外工资
    this.repairCost = 300; // 每次维修固定费用
  }
  
  setRoute(route) {
    this.route = route;
    this.currentStep = 0;
    
    // 从路线中提取目的地
    if (route.steps && route.steps.length > 0) {
      const lastStep = route.steps[route.steps.length - 1];
      const lastLocation = lastStep.polyline.split(';').pop().split(',');
      this.destination = {
        longitude: parseFloat(lastLocation[0]),
        latitude: parseFloat(lastLocation[1])
      };
    }
  }
  
  updatePosition(deltaTime) {
    const now = Date.now();
    const actualDeltaTime = deltaTime || (now - this.lastUpdated) / 1000; // 转换为秒
    this.lastUpdated = now;
    
    // 更新里程和油量
    const moveDistance = (this.speed * 1000 / 3600) * actualDeltaTime; // 米
    this.totalMileage += moveDistance;
    this.mileageSinceWash += moveDistance;
    
    // 消耗油量（每公里消耗约0.1%）
    this.fuel -= (moveDistance / 1000) * 0.1;
    if (this.fuel < 0) this.fuel = 0;
    
    // 随机故障概率：健康值越低，故障概率越高
    // 健康100时约为基准概率，健康降到0时约提升到6倍（并做上限保护）
    const baseFailureProbability = (moveDistance / 100) * 0.0001;
    const healthRiskFactor = 1 + ((100 - this.health) / 100) * 5;
    const failureProbability = Math.min(baseFailureProbability * healthRiskFactor, 0.02);
    if (Math.random() < failureProbability) {
      this.health -= 10; // 故障时健康度下降
      if (this.health < 0) this.health = 0;
      this.isBroken = true;
    }

    // 载货状态下累计本单里程（工厂 -> 仓库）
    if (this.hasCargo) {
      this.cargoMileage += moveDistance;
    }

    // 按百分比扣费：油量和健康值下降才扣费
    const fuelDrop = Math.max(0, this.lastFuel - this.fuel);
    this.profit -= fuelDrop * this.fuelCostPerPercent;
    this.lastFuel = this.fuel;
    this.lastHealth = this.health;
    
    // 如果有路线，按照路线更新位置
    if (this.route && this.route.steps && this.route.steps.length > 0) {
      this.updatePositionByRoute(actualDeltaTime);
    } else if (this.destination) {
      // 否则，直接向目的地移动
      this.updatePositionDirectly(actualDeltaTime);
    } else {
      // 没有目的地时，随机移动
      this.updatePositionRandomly(actualDeltaTime);
    }
    
    // 记录历史位置
    this.recordHistory();
  }
  
  updatePositionByRoute(deltaTime) {
    const currentStep = this.route.steps[this.currentStep];
    if (!currentStep) return;
    
    const polyline = currentStep.polyline.split(';');
    if (this.currentPointIndex >= polyline.length - 1) {
      // 当前步骤完成，移动到下一步
      this.currentStep++;
      this.currentPointIndex = 0;
      
      if (this.currentStep >= this.route.steps.length) {
        // 路线完成
        this.route = null;
        this.currentStep = 0;
        return;
      }
    }
    
    if (this.currentPointIndex === undefined) {
      this.currentPointIndex = 0;
    }
    
    const targetPoint = polyline[this.currentPointIndex].split(',');
    const targetLon = parseFloat(targetPoint[0]);
    const targetLat = parseFloat(targetPoint[1]);
    
    // 计算距离和方向
    const distance = this.calculateDistance(
      this.longitude, this.latitude, targetLon, targetLat
    );
    const direction = this.calculateDirection(
      this.longitude, this.latitude, targetLon, targetLat
    );
    
    // 更新方向
    this.direction = direction;
    
    // 计算移动距离（米）
    const moveDistance = (this.speed * 1000 / 3600) * deltaTime;
    
    if (moveDistance >= distance) {
      // 到达目标点，移动到下一个点
      this.longitude = targetLon;
      this.latitude = targetLat;
      this.currentPointIndex++;
    } else {
      // 向目标点移动
      this.moveInDirection(direction, moveDistance);
    }
  }
  
  updatePositionDirectly(deltaTime) {
    if (!this.destination) return;
    
    // 计算到目的地的距离和方向
    const distance = this.calculateDistance(
      this.longitude, this.latitude, this.destination.longitude, this.destination.latitude
    );
    const direction = this.calculateDirection(
      this.longitude, this.latitude, this.destination.longitude, this.destination.latitude
    );
    
    // 更新方向
    this.direction = direction;
    
    // 计算移动距离（米）
    const moveDistance = (this.speed * 1000 / 3600) * deltaTime;
    
    if (moveDistance >= distance) {
      // 到达目的地
      this.longitude = this.destination.longitude;
      this.latitude = this.destination.latitude;
      this.destination = null;
    } else {
      // 向目的地移动
      this.moveInDirection(direction, moveDistance);
    }
  }
  
  updatePositionRandomly(deltaTime) {
    // 随机改变方向
    this.direction += (Math.random() - 0.5) * 10; // 随机转向
    this.direction = ((this.direction % 360) + 360) % 360; // 确保在0-360范围内
    
    // 计算移动距离（米）
    const moveDistance = (this.speed * 1000 / 3600) * deltaTime;
    
    // 移动
    this.moveInDirection(this.direction, moveDistance);
    
    // 边界检查，保持在北京市区附近
    this.latitude = Math.max(39.7, Math.min(40.1, this.latitude));
    this.longitude = Math.max(116.0, Math.min(116.8, this.longitude));
  }
  
  moveInDirection(direction, distance) {
    // 将方向角度转换为弧度
    const radians = (direction * Math.PI) / 180;
    
    // 地球半径（米）
    const earthRadius = 6371000;
    
    // 计算新的经纬度
    const latRadians = (this.latitude * Math.PI) / 180;
    const lonRadians = (this.longitude * Math.PI) / 180;
    
    const newLatRadians = Math.asin(
      Math.sin(latRadians) * Math.cos(distance / earthRadius) +
      Math.cos(latRadians) * Math.sin(distance / earthRadius) * Math.cos(radians)
    );
    
    const newLonRadians = lonRadians + Math.atan2(
      Math.sin(radians) * Math.sin(distance / earthRadius) * Math.cos(latRadians),
      Math.cos(distance / earthRadius) - Math.sin(latRadians) * Math.sin(newLatRadians)
    );
    
    // 转换回角度
    this.latitude = (newLatRadians * 180) / Math.PI;
    this.longitude = (newLonRadians * 180) / Math.PI;
  }
  
  calculateDistance(lon1, lat1, lon2, lat2) {
    // 使用Haversine公式计算两点间距离
    const R = 6371000; // 地球半径（米）
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
  
  calculateDirection(lon1, lat1, lon2, lat2) {
    // 计算从点1到点2的方向角
    const φ1 = (lat1 * Math.PI) / 180;
    const φ2 = (lat2 * Math.PI) / 180;
    const Δλ = ((lon2 - lon1) * Math.PI) / 180;
    
    const y = Math.sin(Δλ) * Math.cos(φ2);
    const x = Math.cos(φ1) * Math.sin(φ2) - Math.sin(φ1) * Math.cos(φ2) * Math.cos(Δλ);
    const θ = Math.atan2(y, x);
    
    // 转换为0-360度
    return ((θ * 180) / Math.PI + 360) % 360;
  }
  
  hasReachedDestination() {
    // 如果没有目的地，则认为已到达
    if (!this.destination) return true;
    
    // 计算到目的地的距离，如果小于10米则认为已到达
    const distance = this.calculateDistance(
      this.longitude, this.latitude, this.destination.longitude, this.destination.latitude
    );
    
    return distance < 10; // 10米以内认为到达
  }
  
  recordHistory() {
    // 记录最近的100个位置
    this.history.push({
      longitude: this.longitude,
      latitude: this.latitude,
      timestamp: Date.now()
    });
    
    if (this.history.length > 100) {
      this.history.shift();
    }
  }
  
  // 到达POI时的处理
  arriveAtPOI(poiType) {
    switch(poiType) {
      case '工厂':
        // 专程为 reservedOrder 来厂时，装货与写 currentOrder 由 VehicleSimulation 处理
        if (this.reservedOrder) {
          break;
        }
        // 若已有未完成订单，禁止在工厂重置/开启新订单状态
        if (this.currentOrder) {
          this.hasCargo = true;
          this.currentTask = 'going_to_warehouse';
          console.log(`车辆 ${this.id} 已有未完成订单，继续执行原订单`);
          break;
        }
        this.hasCargo = true;
        this.cargoMileage = 0; // 新一单开始，重置载货里程
        this.currentTask = 'going_to_warehouse';
        console.log(`车辆 ${this.id} 在工厂装货完成`);
        break;
      case '仓库':
        // 工厂 -> 仓库算一单，工资和路程正相关
        {
          const baseRevenue = this.baseWagePerOrder + (this.cargoMileage / 1000) * this.wagePerKm;
          const orderRevenue = baseRevenue * this.cargoValueFactor;
          this.profit += orderRevenue;
          this.ordersCompleted += 1;
          this.cargoMileage = 0;
          this.cargoValueFactor = 1;
          this.currentOrder = null;
        }
        this.hasCargo = false;
        this.currentTask = 'going_to_factory';
        console.log(`车辆 ${this.id} 在仓库卸货完成`);
        break;
      case '加油站':
        this.fuel = 100;
        console.log(`车辆 ${this.id} 加油完成`);
        break;
      case '维修':
        this.health = 100;
        this.isBroken = false;
        this.profit -= this.repairCost;
        console.log(`车辆 ${this.id} 维修完成`);
        break;
      case '养车':
        this.mileageSinceWash = 0;
        console.log(`车辆 ${this.id} 洗车完成`);
        break;
    }
  }
  
  // 检查是否需要紧急任务
  needsUrgentTask() {
    // 优先级：故障维修 > 油量不足 > 需要洗车
    if (this.isBroken) {
      return { type: 'repairing', priority: 3 };
    }
    if (this.fuel < 20) {
      return { type: 'refueling', priority: 2 };
    }
    if (this.mileageSinceWash > 50000) { // 50公里需要洗车
      return { type: 'washing', priority: 1 };
    }
    return null;
  }
  
  /** 是否正在派送当前订单（前往订单仓库且载货） */
  isDeliveringOrder() {
    return !!(
      this.currentOrder &&
      this.hasCargo &&
      this.currentTask === 'going_to_warehouse'
    );
  }

  /** 是否允许在工厂从订单池接新单：有未完成订单、或正在派送（载货送仓）时均不可接 */
  canAcceptNewOrderAtFactory() {
    if (this.reservedOrder) return false;
    if (this.currentOrder) return false;
    if (this.hasCargo && this.currentTask === 'going_to_warehouse') return false;
    return true;
  }

  toJSON() {
    const hasDeliveryInProgress = this.isDeliveringOrder();
    const canAcceptNewOrder = this.canAcceptNewOrderAtFactory();

    return {
      id: this.id,
      type: this.type,
      latitude: this.latitude,
      longitude: this.longitude,
      speed: this.speed,
      direction: this.direction,
      status: this.status,
      lastUpdated: this.lastUpdated,
      hasCargo: this.hasCargo,
      fuel: Math.round(this.fuel * 10) / 10,
      health: Math.round(this.health * 10) / 10,
      isBroken: this.isBroken,
      totalMileage: Math.round(this.totalMileage),
      profit: Math.round(this.profit * 10) / 10,
      ordersCompleted: this.ordersCompleted,
      cargoValueFactor: Math.round(this.cargoValueFactor * 100) / 100,
      canAcceptNewOrder,
      hasDeliveryInProgress,
      reservedOrder: this.reservedOrder,
      currentOrder: this.currentOrder,
      currentTask: this.currentTask,
      targetPOI: this.targetPOI
    };
  }
}

module.exports = Vehicle;
