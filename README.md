# Вариант №30. Асинхронное вычисление хеш-сумм файлов

Тема курсовой — веб-приложение с HTTP API для асинхронного вычисления
хеш-сумм файлов по алгоритму PBKDF2.

## Этап 1. Утилита командной строки

Для работы нужен Python 3.11 или новее. Утилита читает JSON из stdin.
Поле `file_b64` содержит байты файла, `salt_b64` — байты соли в Base64,
`iterations` — число итераций. PBKDF2-HMAC-SHA256 использует содержимое файла
как входную последовательность байтов. Результат длиной 32 байта
выводится в stdout в виде JSON с шестнадцатеричным полем `digest`.
При ошибке утилита пишет сообщение в stderr и возвращает код 1.

Максимальный размер файла — 1 МиБ. Пустой файл допустим. Размер соли —
от 1 до 64 байт, число итераций — от 1 до 2 000 000. Для воспроизведения
хеша нужны одинаковые содержимое файла, соль и число итераций.

Три запуска в PowerShell, включая контрольные примеры для `password` и `salt`:

```powershell
'{"file_b64":"cGFzc3dvcmQ=","salt_b64":"c2FsdA==","iterations":1}' | python -m src.calculator
'{"file_b64":"cGFzc3dvcmQ=","salt_b64":"c2FsdA==","iterations":2}' | python -m src.calculator
'{"file_b64":"","salt_b64":"c2FsdA==","iterations":1000}' | python -m src.calculator
```

Значения `digest` по порядку:

```text
120fb6cffcf8b32c43e7225256c4f837a86548c92ccc35480805987cb70be17b
ae4d0c95af6b46d32d0adff928f06dd02a303f8ef3c251dfd6e2d85a95474c43
94fb56af3ea22e5d3ed1b054085b136ca301b75d8b406c802c489479f27387c6
```

Ввод из файла:

```powershell
$task = @{
    file_b64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes("example.bin"))
    salt_b64 = "c2FsdA=="
    iterations = 200000
}
$task | ConvertTo-Json -Compress | python -m src.calculator
```

## Этап 2. HTTP API с файловым хранилищем

Запуск из корня репозитория в PowerShell:

```powershell
.\run.bat student demo --db variant30.shelf
```

Сервер слушает `127.0.0.1:8000`. Порт и адрес задаются через `--port`
и `--host`. Логин и пароль — обязательные аргументы. Все маршруты
используют HTTP Basic по [RFC 7617](https://www.rfc-editor.org/rfc/rfc7617).
Успешные операции возвращают `200 OK` и XML. Ответ `401 Unauthorized`
содержит `WWW-Authenticate`, неверные параметры дают `400`,
а неизвестный маршрут или отсутствующая запись — `404`.

Записи этапа 2 сохраняются через `shelve` с файловым бэкендом `dbm.dumb`.
Один экземпляр приложения обслуживает один набор файлов хранилища.
Один фоновый поток выполняет задания, передавая `Message.data`
в stdin CLI через `subprocess`. Новый `Message` сразу возвращается
с полями `started=0` и `done=0`. При запуске вычисления сервер записывает
`started`, после завершения — `done` и запись `Feedback`. Успешный
результат находится в `response`, ошибка CLI — в `failure`.
В `status` записывается `success` или `failure`. Задачи с `done=0`
ставятся в очередь снова при запуске сервера. С `--test-mode` фоновый
поток возвращает `test-mode` без запуска CLI.

### Маршруты из таблицы 30

У всех маршрутов префикс `/public/api`.

| № | Метод | Путь | Параметры |
|---|---|---|---|
| 1.1 | POST | `/new/person` | XML `<person>` |
| 1.2 | DELETE | `/terminate/person/:key` | Ключ в пути |
| 1.3 | POST | `/search/person` | XML `<search>` |
| 1.4 | GET | `/single/person?key=1` | Ключ в запросе |
| 2.1 | POST | `/new/message` | XML `<message>` |
| 2.2 | DELETE | `/terminate/message/:key` | Ключ в пути |
| 2.3 | POST | `/search/message/:person` | Ключ владельца и XML `<search>` |
| 2.4 | GET | `/single/message?key=1` | Ключ в запросе |
| 3.1 | POST | `/search/feedback/:message` | Ключ задания и XML `<search>` |
| 3.2 | GET | `/single/feedback?key=1` | Ключ в запросе |
| 4.1 | POST | `/search/report` | Без параметров |

Пример тел создания в XML:

```xml
<person><platform>Windows</platform><user_agent>example</user_agent></person>
```

```xml
<message>
  <person>1</person>
  <tags>demo</tags>
  <data>{"file_b64":"YWJj","salt_b64":"c2FsdA==","iterations":1000}</data>
</message>
```

`key` выдаётся сервером. `datetime` задаётся в секундах Unix, по
умолчанию используется текущее время. `tags` по умолчанию пустое.
Поля поиска сравниваются на точное равенство. Например,
`<search><platform>Windows</platform></search>` ищет записи Person
по платформе. `<search/>` возвращает все записи в области маршрута.
Результат поиска — `<results>` со списком записей. При удалении Person
удаляются его Message, при удалении Message — связанные Feedback.

Отчёт по формуле (30) соединяет `Person.key = Message.person`, отбирает
`Message.datetime > now - 8 минут` и возвращает уникальные пары
`Message.data` и `Person.platform` как `<row>` внутри `<report>`.
Временная граница исключается. Отчёт включает задачи на любой стадии.

### Пример с клиентом Python

После запуска сервера выполни этот пример из корня репозитория.
Вместо `example.bin` укажи путь к своему файлу.

```python
import base64
import json
import time
from pathlib import Path

from src.client import ApiClient

api = ApiClient("http://127.0.0.1:8000", "student", "demo")
_, person = api.public_api_new_person(platform="Windows", user_agent="demo")
task = {
    "file_b64": base64.b64encode(Path("example.bin").read_bytes()).decode(),
    "salt_b64": "c2FsdA==",
    "iterations": 200000,
}
_, message = api.public_api_new_message(
    person=int(person.findtext("key")), data=json.dumps(task), tags="demo",
)
key = int(message.findtext("key"))
deadline = time.monotonic() + 15
while time.monotonic() < deadline:
    status, result = api.public_api_search_feedback(key)
    if status != 200:
        raise RuntimeError(result.findtext("message"))
    feedback = result.find("feedback")
    if feedback is not None:
        print(feedback.findtext("response") or feedback.findtext("failure"))
        break
    time.sleep(0.1)
else:
    raise TimeoutError(f"Задание {key} ещё выполняется")
```

### Проверка файлового этапа

```powershell
python -m pip install -r requirements-test.txt
python -m coverage run --branch --source=src --omit='src/calculator.py,src/sqlite_storage.py' -m unittest tests.test_api
python -m coverage report -m
```

Модель `RuleBasedStateMachine` посылает HTTP-запросы через `ApiClient`,
проверяет все 11 маршрутов, сверяет записи с независимыми словарями,
проверяет каскадное удаление, авторизацию и границу отчёта.
Утилита CLI проверяется отдельно тремя примерами этапа 1.
