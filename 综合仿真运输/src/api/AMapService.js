// 使用动态导入或降级版本的fetch
const fetch = (...args) => import('node-fetch').then(({default: fetch}) => fetch(...args));

class AMapService {
  constructor() {
    this.apiKey = process.env.AMAP_KEY;
    this.baseUrl = 'https://restapi.amap.com/v3';
  }
  
  /**
   * 获取驾车路线规划
   * @param {string} origin - 起点坐标，格式：经度,纬度
   * @param {string} destination - 终点坐标，格式：经度,纬度
   * @returns {Promise} 路线规划结果
   */
  async getDrivingRoute(origin, destination) {
    if (!this.apiKey) {
      console.warn('未配置高德地图API密钥，将使用模拟数据');
      return this.getMockRoute(origin, destination);
    }
    
    const url = `${this.baseUrl}/direction/driving?` +
      new URLSearchParams({
        origin,
        destination,
        key: this.apiKey,
        extensions: 'all',
        strategy: '0' // 0-最快路线
      });
    
    try {
      const response = await fetch(url);
      const data = await response.json();
      
      if (data.status === '1' && data.route) {
        return data.route;
      } else {
        console.error('高德地图API返回错误:', data.info);
        return this.getMockRoute(origin, destination);
      }
    } catch (error) {
      console.error('调用高德地图API失败:', error);
      return this.getMockRoute(origin, destination);
    }
  }
  
  /**
   * 获取地理编码
   * @param {string} address - 地址字符串
   * @returns {Promise} 地理编码结果
   */
  async getGeocode(address) {
    if (!this.apiKey) {
      console.warn('未配置高德地图API密钥，将返回模拟数据');
      return this.getMockGeocode(address);
    }
    
    const url = `${this.baseUrl}/geocode/geo?` +
      new URLSearchParams({
        address,
        key: this.apiKey,
        city: '北京'
      });
    
    try {
      const response = await fetch(url);
      const data = await response.json();
      
      if (data.status === '1' && data.geocodes && data.geocodes.length > 0) {
        return data.geocodes[0];
      } else {
        console.error('地理编码失败:', data.info);
        return this.getMockGeocode(address);
      }
    } catch (error) {
      console.error('调用地理编码API失败:', error);
      return this.getMockGeocode(address);
    }
  }
  
  /**
   * 获取逆地理编码
   * @param {string} location - 坐标，格式：经度,纬度
   * @returns {Promise} 逆地理编码结果
   */
  async getReverseGeocode(location) {
    if (!this.apiKey) {
      console.warn('未配置高德地图API密钥，将返回模拟数据');
      return this.getMockReverseGeocode(location);
    }
    
    const url = `${this.baseUrl}/geocode/regeo?` +
      new URLSearchParams({
        location,
        key: this.apiKey,
        extensions: 'all'
      });
    
    try {
      const response = await fetch(url);
      const data = await response.json();
      
      if (data.status === '1' && data.regeocode) {
        return data.regeocode;
      } else {
        console.error('逆地理编码失败:', data.info);
        return this.getMockReverseGeocode(location);
      }
    } catch (error) {
      console.error('调用逆地理编码API失败:', error);
      return this.getMockReverseGeocode(location);
    }
  }
  
  /**
   * 获取实时交通状况
   * @param {string} rectangle - 矩形区域，格式：左下经度,左下纬度,右上经度,右上纬度
   * @returns {Promise} 交通状况结果
   */
  async getTrafficStatus(rectangle) {
    if (!this.apiKey) {
      console.warn('未配置高德地图API密钥，将返回模拟数据');
      return this.getMockTrafficStatus(rectangle);
    }
    
    const url = `${this.baseUrl}/traffic/status/rectangle?` +
      new URLSearchParams({
        rectangle,
        key: this.apiKey
      });
    
    try {
      const response = await fetch(url);
      const data = await response.json();
      
      if (data.status === '1' && data.trafficinfo) {
        return data.trafficinfo;
      } else {
        console.error('获取交通状况失败:', data.info);
        return this.getMockTrafficStatus(rectangle);
      }
    } catch (error) {
      console.error('调用交通状况API失败:', error);
      return this.getMockTrafficStatus(rectangle);
    }
  }
  
  // 模拟数据方法 - 改进版，生成更接近真实道路的路线
  getMockRoute(origin, destination) {
    const [originLon, originLat] = origin.split(',').map(parseFloat);
    const [destLon, destLat] = destination.split(',').map(parseFloat);
    
    // 计算距离，根据距离决定路线点的数量
    const distance = this.calculateDistance(originLon, originLat, destLon, destLat);
    const steps = Math.max(30, Math.min(100, Math.floor(distance / 100))); // 每100米一个点，最少30个，最多100个
    
    // 生成更平滑的路线点，模拟道路的弯曲
    const points = [];
    
    // 计算中间控制点，使路线更弯曲（模拟道路）
    const midLon = (originLon + destLon) / 2;
    const midLat = (originLat + destLat) / 2;
    
    // 添加一些偏移，模拟道路不是完全直线
    const offsetLon = (destLon - originLon) * 0.1 * (Math.random() - 0.5);
    const offsetLat = (destLat - originLat) * 0.1 * (Math.random() - 0.5);
    
    const controlLon = midLon + offsetLon;
    const controlLat = midLat + offsetLat;
    
    // 使用贝塞尔曲线生成平滑路线点
    for (let i = 0; i <= steps; i++) {
      const t = i / steps;
      
      // 二次贝塞尔曲线：B(t) = (1-t)²P₀ + 2(1-t)tP₁ + t²P₂
      const lon = Math.pow(1 - t, 2) * originLon + 
                  2 * (1 - t) * t * controlLon + 
                  Math.pow(t, 2) * destLon;
      const lat = Math.pow(1 - t, 2) * originLat + 
                  2 * (1 - t) * t * controlLat + 
                  Math.pow(t, 2) * destLat;
      
      // 添加小的随机波动，模拟道路的微小弯曲
      const noiseLon = (Math.random() - 0.5) * 0.002;
      const noiseLat = (Math.random() - 0.5) * 0.002;
      
      points.push(`${(lon + noiseLon).toFixed(6)},${(lat + noiseLat).toFixed(6)}`);
    }
    
    // 计算实际路线距离（考虑弯曲）
    let routeDistance = 0;
    for (let i = 1; i < points.length; i++) {
      const [lon1, lat1] = points[i - 1].split(',').map(parseFloat);
      const [lon2, lat2] = points[i].split(',').map(parseFloat);
      routeDistance += this.calculateDistance(lon1, lat1, lon2, lat2);
    }
    
    return {
      paths: [{
        distance: Math.floor(routeDistance),
        duration: Math.floor(routeDistance / 1000 * 60), // 假设平均速度60km/h
        steps: [{
          polyline: points.join(';'),
          distance: Math.floor(routeDistance),
          duration: Math.floor(routeDistance / 1000 * 60)
        }]
      }]
    };
  }
  
  getMockGeocode(address) {
    return {
      formatted_address: address,
      location: `${116.3 + Math.random() * 0.4},${39.8 + Math.random() * 0.4}`,
      addressComponent: {
        city: '北京市',
        district: ['朝阳区', '海淀区', '西城区', '东城区'][Math.floor(Math.random() * 4)],
        street: '模拟街道',
        streetNumber: Math.floor(Math.random() * 100) + 1
      }
    };
  }
  
  getMockReverseGeocode(location) {
    return {
      formatted_address: '北京市朝阳区模拟街道1号',
      addressComponent: {
        city: '北京市',
        district: '朝阳区',
        street: '模拟街道',
        streetNumber: '1号'
      },
      road: {
        name: '模拟道路'
      }
    };
  }
  
  getMockTrafficStatus(rectangle) {
    // 生成模拟交通状况
    const statuses = ['畅通', '缓行', '拥堵'];
    const levelValues = ['1', '2', '3'];
    
    const roads = [];
    const roadCount = Math.floor(Math.random() * 5) + 5;
    
    for (let i = 0; i < roadCount; i++) {
      const randomIndex = Math.floor(Math.random() * 3);
      roads.push({
        name: `模拟道路${i + 1}`,
        status: statuses[randomIndex],
        statusDesc: statuses[randomIndex],
        level: levelValues[randomIndex],
        polyline: this.generateRandomPolyline(rectangle)
      });
    }
    
    return {
      description: '模拟交通数据',
      evaluation: {
        status: '0',
        description: '道路整体畅通'
      },
      roads
    };
  }
  
  generateRandomPolyline(rectangle) {
    const [minLon, minLat, maxLon, maxLat] = rectangle.split(',').map(parseFloat);
    const points = [];
    const pointCount = Math.floor(Math.random() * 5) + 5;
    
    for (let i = 0; i < pointCount; i++) {
      const lon = minLon + Math.random() * (maxLon - minLon);
      const lat = minLat + Math.random() * (maxLat - minLat);
      points.push(`${lon.toFixed(6)},${lat.toFixed(6)}`);
    }
    
    return points.join(';');
  }
  
  calculateDistance(lon1, lat1, lon2, lat2) {
    const R = 6371e3; // 地球半径（米）
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

module.exports = new AMapService();
