import requests
import json
import logging
from typing import Optional

# Настройка логирования
logging.basicConfig(
    level=logging.DEBUG,  # Уровень DEBUG записывает всё, включая сырые данные
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler("C:/Users/user/OneDrive/Рабочий стол/Ферма/farm_guardian/farm_guardian.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("LLMClient")

class LLMClientError(Exception):
    pass

class AnythingLLMClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        workspace: str,
        timeout: int = 60,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.workspace = workspace
        self.timeout = timeout
        logger.info(f"Инициализирован клиент для воркспейса: {workspace}")

    def ask(self, prompt: str) -> str:
        """
        Отправляет запрос в AnythingLLM
        Возвращает ТОЛЬКО текст ответа модели
        """
        url = f"{self.base_url}/api/v1/workspace/{self.workspace}/chat"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "message": prompt,
            "mode": "chat", 
        }

        logger.info(f"Отправка запроса к {url}")
        logger.debug(f"Payload: {json.dumps(payload, ensure_ascii=False)}")

        try:
            response = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=self.timeout,
            )
            logger.info(f"Получен ответ. Статус-код: {response.status_code}")
            
        except requests.RequestException as e:
            logger.error(f"Ошибка соединения: {e}", exc_info=True)
            raise LLMClientError(f"Ошибка соединения с AnythingLLM: {e}")

        if response.status_code != 200:
            logger.error(f"API вернул ошибку {response.status_code}: {response.text}")
            raise LLMClientError(
                f"AnythingLLM вернул {response.status_code}: {response.text}"
            )

        try:
            data = response.json()
            # Логируем ВЕСЬ пришедший JSON, чтобы понять структуру
            logger.debug(f"Сырой ответ от API: {json.dumps(data, indent=2, ensure_ascii=False)}")
        except json.JSONDecodeError:
            logger.error("Не удалось декодировать JSON из ответа")
            raise LLMClientError("Ответ AnythingLLM не JSON")

        # Добавил textResponse, так как AnythingLLM часто использует это поле
        answer = (
            data.get("textResponse")
            or data.get("text")
            or data.get("response")
            or data.get("message")
        )

        if not answer:
            logger.warning("Поля ответа (textResponse, text, response, message) пусты или отсутствуют")
            raise LLMClientError("Пустой ответ от модели")

        logger.info("Успешно извлечен текст ответа")
        return answer.strip()

# --- ТЕСТОВЫЙ БЛОК ---
if __name__ == "__main__":
    API_KEY = "K90ZAK7-VEMMVAN-KCF11C4-QG5A1VF"
    BASE_URL = "http://localhost:3001"
    WORKSPACE_SLUG = "moya-rabochaya-oblast"

    try:
        print(f"Подключение к {BASE_URL} (Workspace: {WORKSPACE_SLUG})...")
        client = AnythingLLMClient(BASE_URL, API_KEY, WORKSPACE_SLUG)
        response = client.ask("Привет! Ты на связи?")
        print(f"\nОтвет модели:\n{response}")
        print("\n[УСПЕХ] Связь установлена.")
    except Exception as e:
        print(f"\n[ОШИБКА] Проверьте лог-файл farm_guardian.log")
        logger.error(f"Ошибка в тестовом блоке: {e}")
