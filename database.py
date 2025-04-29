from typing import List
import logging
import asyncpg
from asyncpg.pool import Pool

# logging
logging.basicConfig(
    level=logging.WARNING,  # Уровень логирования
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',  # Формат сообщения
    handlers=[
        logging.FileHandler("app.log"),  # Запись логов в файл "app.log"
        logging.StreamHandler()  # Вывод логов на консоль
    ]
)
logger = logging.getLogger(__name__)


class AsyncDatabase:
    def __init__(self, db_name, user, password, host='localhost', port=5432, min_size=10, max_size=200):
        self.db_name = db_name
        self.user = user
        self.password = password
        self.host = host
        self.port = port
        self.pool: Pool = None
        self.min_size = min_size
        self.max_size = max_size

    # ----------helping_methods-------------
    async def connect(self):
        try:
            self.pool = await asyncpg.create_pool(
                database=self.db_name,
                user=self.user,
                password=self.password,
                host=self.host,
                port=self.port,
                min_size=self.min_size,
                max_size=self.max_size
            )
            print("[DB] Connection to the database was successfully established")
        except Exception as e:
            print(f"[DB] Error when connecting to the database: {e}")
            logger.error("Ошибка при подключении к базе данных:", e)

    async def close(self):
        if self.pool:
            await self.pool.close()
            print("[DB] The connection to the database is closed.")

    # Этот метод выполняет SQL-запрос на изменение данных (например, INSERT, UPDATE, DELETE).
    # Метод принимает SQL-запрос как строку и параметры для подстановки в запрос.
    # Он использует пул соединений для выполнения запроса и открывает транзакцию для обеспечения атомарности операций.
    async def execute(self, query: str, *args):
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(query, *args)

    # Этот метод выполняет SQL-запрос, который возвращает несколько строк данных.
    # Он принимает SQL-запрос и параметры для подстановки.
    # Метод возвращает результат в виде списка строк (каждая строка представляет собой запись в таблице).
    async def fetch(self, query: str, *args):
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                return await connection.fetch(query, *args)

    # Этот метод выполняет SQL-запрос, который возвращает одну строку данных.
    # Подходит для запросов, которые должны вернуть только одну запись.
    # Метод возвращает одну строку из результата запроса.
    async def fetchrow(self, query: str, *args):
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                return await connection.fetchrow(query, *args)

    # Этот метод выполняет SQL-запрос, который возвращает одно значение
    # (например, результат агрегации или значения из одного столбца).
    # Метод принимает индекс столбца для возвращаемого значения.
    # По умолчанию индекс равен 0, что означает первый столбец.
    async def fetchval(self, query: str, *args, column: int = 0):
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                return await connection.fetchval(query, *args, column=column)

    # Есть ли пользователь с тг айди в таблице
    async def user_exists(self, tg_user_id: int) -> bool:
        query = "SELECT EXISTS(SELECT 1 FROM user_info WHERE tg_user_id = $1)"
        try:
            result = await self.fetchval(query, tg_user_id)
            return result
        except Exception as e:
            #nt(f"[DB] Ошибка при проверке существования пользователя: {e}")
            return False
#-------------------------
#-------messages----------
#-------------------------
    # Получение последнего сообщения
    async def get_last_messages_by_user_id(self, tg_user_id: int) -> List[int]:
        try:
            query = """
                    SELECT last_message_ids FROM user_info
                    WHERE tg_user_id = $1;
                    """
            last_message = await self.fetchval(query, tg_user_id)

            if last_message is not None:
                #print(f"[DB] Последнее сообщение для пользователя {tg_user_id}: {last_message}")
                return last_message
            else:
                #print(f"[DB] Последнее сообщение для пользователя {tg_user_id} не найдено.")
                return []
        except Exception as e:
            #print(f"[DB] Ошибка при получении последнего сообщения для пользователя {tg_user_id}: {e}")
            return []

    async def set_last_message_by_user_id(self, tg_user_id, last_message):
        try:
            if last_message is None:
                #print(f"[DB] Последнее сообщение для пользователя {tg_user_id} равно None, обновление не требуется.")
                return

            # Преобразуем last_message в список, если это не список
            if not isinstance(last_message, list):
                last_message = [last_message]

            exists_query = """
                SELECT EXISTS(
                    SELECT 1 FROM user_info WHERE tg_user_id = $1
                );
            """
            exists = await self.fetchval(exists_query, tg_user_id)

            if exists:
                # Обновляем массив, добавляя новые значения
                update_query = """
                    UPDATE user_info
                    SET last_message_ids = ARRAY(
                        SELECT unnest(last_message_ids) 
                        UNION 
                        SELECT unnest($2::bigint[])
                    )
                    WHERE tg_user_id = $1;
                """
                await self.execute(update_query, tg_user_id, last_message)
                #print(f"[DB] Последнее сообщение для пользователя {tg_user_id} обновлено")
            else:
                # Вставляем новые значения в массив
                insert_query = """
                    INSERT INTO user_info (tg_user_id, last_message_ids)
                    VALUES ($1, $2);
                """
                await self.execute(insert_query, tg_user_id, last_message)
                #print(f"[DB] Добавлена новая запись для пользователя {tg_user_id} с последним сообщением")

        except Exception as e:
            logger.error(f"Ошибка при установке последнего сообщения для пользователя {tg_user_id}: {e}")
            #print(f"Ошибка при установке последнего сообщения для пользователя {tg_user_id}: {e}")

    async def clear_last_message_ids_by_user_id(self, tg_user_id):
        try:
            exists_query = """
                SELECT EXISTS(
                    SELECT 1 FROM user_info WHERE tg_user_id = $1
                );
            """
            exists = await self.fetchval(exists_query, tg_user_id)

            if exists:
                # Очищаем массив
                update_query = """
                    UPDATE user_info
                    SET last_message_ids = ARRAY[]::bigint[]
                    WHERE tg_user_id = $1;
                """
                await self.execute(update_query, tg_user_id)
                #print(f"[DB] Поле last_message_ids для пользователя {tg_user_id} очищено")
            else:
                logger.error(f"[DB] Пользователь {tg_user_id} не найден, очистка не требуется")
                #print(f"[DB] Пользователь {tg_user_id} не найден, очистка не требуется")

        except Exception as e:
            logger.error(f"Ошибка при очистке поля last_message_ids для пользователя {tg_user_id}: {e}")
            #print(f"Ошибка при очистке поля last_message_ids для пользователя {tg_user_id}: {e}")
#-------------------------
#------------user---------
#-------------------------

    async def user_registration(self, tg_user_id: int, role: str):
        try:
            query = '''
                INSERT INTO user_info (tg_user_id, role, last_message_ids)
                VALUES ($1, $2, ARRAY[]::BIGINT[])
            '''
            await self.execute(query, tg_user_id, role)
        except Exception as e:
            logger.error(f"Ошибка при регистрации пользователя {tg_user_id}: {e}")



    async def client_registration(self, tg_user_id, phone_number):
        try:
            insert_query = """
                                INSERT INTO client_info (tg_user_id, tel_num)
                                VALUES ($1, $2);
                            """
            await self.execute(insert_query, tg_user_id, phone_number)
        except Exception as e:
            logger.error(f"Ошибка при регистрации клиента {tg_user_id}: {e}")

    async def admin_registration(self, tg_user_id):
        try:
            insert_query = """
                                            INSERT INTO admin_info (tg_user_id)
                                            VALUES ($1);
                                        """
            await self.execute(insert_query, tg_user_id)
        except Exception as e:
            logger.error(f"Ошибка при регистрации админа {tg_user_id}: {e}")
