"""
VIN Parser для emex.ru
Парсер для получения информации о запчастях по VIN коду автомобиля
"""
import os
import json
import time
import logging
from typing import Dict, List, Optional
from datetime import datetime

try:
    import requests
    from bs4 import BeautifulSoup
    from flask import Flask, request, jsonify
    from flask_cors import CORS
except ImportError:
    print("Установите необходимые зависимости: pip install -r requirements.txt")
    exit(1)

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

class EmexVINParser:
    """Класс для парсинга данных о запчастях с emex.ru по VIN коду"""
    
    def __init__(self, username: Optional[str] = None, password: Optional[str] = None):
        self.base_url = "https://emex.ru"
        self.session = requests.Session()
        self.username = username or os.getenv('EMEX_USERNAME')
        self.password = password or os.getenv('EMEX_PASSWORD')
        self.is_authenticated = False
        
        # Заголовки для имитации браузера
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
        })
    
    def authenticate(self) -> bool:
        """Аутентификация на сайте emex.ru"""
        if not self.username or not self.password:
            logger.warning("Учетные данные не предоставлены. Работа в режиме без авторизации.")
            return False
        
        try:
            login_url = f"{self.base_url}/auth/login"
            login_data = {
                'login': self.username,
                'password': self.password
            }
            
            response = self.session.post(login_url, data=login_data, timeout=30)
            
            if response.status_code == 200:
                self.is_authenticated = True
                logger.info("Успешная аутентификация на emex.ru")
                return True
            else:
                logger.error(f"Ошибка аутентификации: {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"Ошибка при аутентификации: {str(e)}")
            return False
    
    def decode_vin(self, vin_code: str) -> Dict:
        """Декодирование VIN кода для получения информации об автомобиле"""
        try:
            # Валидация VIN кода
            if not vin_code or len(vin_code) != 17:
                return {
                    'error': 'Неверный формат VIN кода. Должно быть 17 символов.',
                    'vin': vin_code
                }
            
            # Используем публичный API для декодирования VIN
            nhtsa_url = f"https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVin/{vin_code}?format=json"
            response = requests.get(nhtsa_url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                results = data.get('Results', [])
                
                vehicle_info = {}
                for item in results:
                    if item.get('Value'):
                        vehicle_info[item.get('Variable')] = item.get('Value')
                
                return {
                    'vin': vin_code,
                    'vehicle_info': vehicle_info,
                    'decoded': True
                }
            else:
                return {
                    'error': 'Не удалось декодировать VIN',
                    'vin': vin_code
                }
                
        except Exception as e:
            logger.error(f"Ошибка при декодировании VIN: {str(e)}")
            return {
                'error': str(e),
                'vin': vin_code
            }
    
    def search_parts_by_vin(self, vin_code: str, part_name: Optional[str] = None) -> Dict:
        """Поиск запчастей по VIN коду на emex.ru"""
        try:
            # Сначала декодируем VIN
            vin_info = self.decode_vin(vin_code)
            
            if 'error' in vin_info:
                return vin_info
            
            # Формируем URL для поиска на emex.ru
            search_url = f"{self.base_url}/search/vin/{vin_code}"
            
            if part_name:
                search_url += f"?query={part_name}"
            
            response = self.session.get(search_url, timeout=30)
            
            if response.status_code != 200:
                return {
                    'error': f'Ошибка при запросе к emex.ru: {response.status_code}',
                    'vin': vin_code
                }
            
            # Парсим HTML
            soup = BeautifulSoup(response.text, 'html.parser')
            parts = self._parse_parts_from_html(soup)
            
            return {
                'vin': vin_code,
                'vehicle_info': vin_info.get('vehicle_info', {}),
                'parts': parts,
                'total_parts': len(parts),
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Ошибка при поиске запчастей: {str(e)}")
            return {
                'error': str(e),
                'vin': vin_code
            }
    
    def _parse_parts_from_html(self, soup: BeautifulSoup) -> List[Dict]:
        """Извлечение данных о запчастях из HTML"""
        parts = []
        
        try:
            # Ищем элементы с информацией о запчастях
            # Примечание: Структура сайта может меняться, нужно адаптировать селекторы
            
            part_items = soup.find_all('div', class_='part-item') or \
                        soup.find_all('tr', class_='search-row') or \
                        soup.find_all('div', {'data-type': 'part'})
            
            for item in part_items:
                part_data = self._extract_part_info(item)
                if part_data:
                    parts.append(part_data)
            
            if not parts:
                logger.info("Запчасти не найдены или структура сайта изменилась")
                
        except Exception as e:
            logger.error(f"Ошибка при парсинге HTML: {str(e)}")
        
        return parts
    
    def _extract_part_info(self, element) -> Optional[Dict]:
        """Извлечение информации об отдельной запчасти"""
        try:
            part_info = {}
            
            # Артикул
            article = element.find(class_='article') or element.find('td', {'data-title': 'Артикул'})
            if article:
                part_info['article'] = article.get_text(strip=True)
            
            # Название
            name = element.find(class_='name') or element.find(class_='part-name')
            if name:
                part_info['name'] = name.get_text(strip=True)
            
            # Цена
            price = element.find(class_='price') or element.find('td', {'data-title': 'Цена'})
            if price:
                price_text = price.get_text(strip=True)
                part_info['price'] = price_text
            
            # Наличие
            availability = element.find(class_='availability') or element.find('td', {'data-title': 'Наличие'})
            if availability:
                part_info['availability'] = availability.get_text(strip=True)
            
            # Производитель
            manufacturer = element.find(class_='manufacturer') or element.find(class_='brand')
            if manufacturer:
                part_info['manufacturer'] = manufacturer.get_text(strip=True)
            
            # Срок доставки
            delivery = element.find(class_='delivery') or element.find('td', {'data-title': 'Срок'})
            if delivery:
                part_info['delivery_time'] = delivery.get_text(strip=True)
            
            return part_info if part_info else None
            
        except Exception as e:
            logger.error(f"Ошибка при извлечении информации о запчасти: {str(e)}")
            return None
    
    def get_part_details(self, article: str) -> Dict:
        """Получение детальной информации о запчасти по артикулу"""
        try:
            search_url = f"{self.base_url}/search/articles/{article}"
            response = self.session.get(search_url, timeout=30)
            
            if response.status_code != 200:
                return {
                    'error': f'Ошибка при запросе: {response.status_code}',
                    'article': article
                }
            
            soup = BeautifulSoup(response.text, 'html.parser')
            details = self._parse_part_details(soup, article)
            
            return details
            
        except Exception as e:
            logger.error(f"Ошибка при получении деталей запчасти: {str(e)}")
            return {
                'error': str(e),
                'article': article
            }
    
    def _parse_part_details(self, soup: BeautifulSoup, article: str) -> Dict:
        """Парсинг детальной информации о запчасти"""
        details = {
            'article': article,
            'offers': []
        }
        
        try:
            offers = soup.find_all('div', class_='offer-item') or \
                    soup.find_all('tr', class_='offer-row')
            
            for offer in offers:
                offer_data = {
                    'price': None,
                    'availability': None,
                    'warehouse': None,
                    'delivery_time': None
                }
                
                # Извлекаем данные предложения
                price = offer.find(class_='price')
                if price:
                    offer_data['price'] = price.get_text(strip=True)
                
                availability = offer.find(class_='availability')
                if availability:
                    offer_data['availability'] = availability.get_text(strip=True)
                
                warehouse = offer.find(class_='warehouse')
                if warehouse:
                    offer_data['warehouse'] = warehouse.get_text(strip=True)
                
                delivery = offer.find(class_='delivery')
                if delivery:
                    offer_data['delivery_time'] = delivery.get_text(strip=True)
                
                if any(offer_data.values()):
                    details['offers'].append(offer_data)
        
        except Exception as e:
            logger.error(f"Ошибка при парсинге деталей: {str(e)}")
        
        return details


# Flask API endpoints
parser = EmexVINParser()

@app.route('/')
def home():
    """Главная страница API"""
    return jsonify({
        'service': 'VIN Parser для emex.ru',
        'version': '1.0.0',
        'endpoints': {
            '/api/decode-vin/<vin>': 'Декодирование VIN кода',
            '/api/search-parts/<vin>': 'Поиск запчастей по VIN',
            '/api/part-details/<article>': 'Детальная информация о запчасти',
            '/health': 'Проверка состояния сервиса'
        },
        'status': 'active'
    })

@app.route('/health')
def health_check():
    """Проверка работоспособности сервиса"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat()
    })

@app.route('/api/decode-vin/<vin>', methods=['GET'])
def decode_vin(vin):
    """Декодирование VIN кода"""
    try:
        result = parser.decode_vin(vin.upper())
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/search-parts/<vin>', methods=['GET'])
def search_parts(vin):
    """Поиск запчастей по VIN коду"""
    try:
        part_name = request.args.get('part_name')
        result = parser.search_parts_by_vin(vin.upper(), part_name)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/part-details/<article>', methods=['GET'])
def part_details(article):
    """Получение детальной информации о запчасти"""
    try:
        result = parser.get_part_details(article)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/authenticate', methods=['POST'])
def authenticate():
    """Аутентификация на emex.ru"""
    try:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        
        if not username or not password:
            return jsonify({'error': 'Username и password обязательны'}), 400
        
        global parser
        parser = EmexVINParser(username, password)
        success = parser.authenticate()
        
        return jsonify({
            'authenticated': success,
            'message': 'Успешная аутентификация' if success else 'Ошибка аутентификации'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    port = int(os.getenv('PORT', 8000))
    app.run(host='0.0.0.0', port=port, debug=False)
