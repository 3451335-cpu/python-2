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
