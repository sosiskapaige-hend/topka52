# Quantum

Telegram-бот Quantum — реконструкция интерфейса по спецификации (Часть 1).

## Быстрый старт

1. Создайте бота через [@BotFather](https://t.me/BotFather) и получите токен.

2. Скопируйте конфиг:
   ```powershell
   copy .env.example .env
   ```

3. Укажите токен в `.env`:
   ```
   BOT_TOKEN=123456:ABC...
   ```

4. (Опционально) URL Mini App для кнопки «🚀 Открыть приложение»:
   ```
   WEBAPP_URL=https://your-app.example.com
   ```
   Без URL кнопка открывает заглушку с заголовком раздела.

5. Установите зависимости и запустите:
   ```powershell
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   python main.py
   ```

6. В Telegram отправьте боту команду `/menu`.

## Реализованные экраны

- 👋 Главное меню
- 🔗 Связки (статистика операций, выбор и активные связки)
- 📊 Выбрать связку (сетка монет 2×N, SOL на всю ширину)
- ⚡ Активные связки (пустое состояние)
- 💼 Кошелек (профиль, ID, баланс)

Нераскрытые в спецификации разделы показывают только заголовок и кнопку «⬅️ Назад».

## Структура

```
quantum-bot/
  bot/
    constants.py   # callback_data, список монет
    keyboards.py   # Inline-клавиатуры
    texts.py       # тексты сообщений
    storage.py     # данные пользователей (JSON)
    handlers.py    # обработчики
  main.py
  requirements.txt
  .env.example
```

Данные пользователей сохраняются в `data/users.json`.
