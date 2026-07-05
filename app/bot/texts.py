"""Lightweight i18n. Central place for user-facing strings in 4 languages.

Usage: ``t("menu.title", lang)``. Falls back to German, then to the key itself.
This keeps handlers free of hard-coded copy and makes adding a language a matter
of extending the dictionaries below.
"""

from __future__ import annotations

SUPPORTED_LANGUAGES = ("de", "en", "ru", "uk")
DEFAULT_LANGUAGE = "de"

_TEXTS: dict[str, dict[str, str]] = {
    "start.greeting": {
        "de": "👋 Willkommen beim <b>Deal-Jäger</b>!\n\n"
        "Ich durchsuche laufend Marktplätze und melde dir nur die wirklich "
        "guten Angebote. Leg eine Suchregel an und ich erledige den Rest.",
        "en": "👋 Welcome to the <b>Deal Hunter</b>!\n\n"
        "I continuously scan marketplaces and alert you only to the truly good "
        "offers. Create a search rule and I'll do the rest.",
        "ru": "👋 Добро пожаловать в <b>Охотник за скидками</b>!\n\n"
        "Я постоянно сканирую площадки и присылаю только действительно выгодные "
        "предложения. Создай правило поиска — остальное сделаю я.",
        "uk": "👋 Ласкаво просимо до <b>Мисливця за знижками</b>!\n\n"
        "Я постійно скную майданчики й надсилаю лише справді вигідні "
        "пропозиції. Створи правило пошуку — решту зроблю я.",
    },
    "menu.title": {
        "de": "🏠 <b>Hauptmenü</b>\nWas möchtest du tun?",
        "en": "🏠 <b>Main menu</b>\nWhat would you like to do?",
        "ru": "🏠 <b>Главное меню</b>\nЧто ты хочешь сделать?",
        "uk": "🏠 <b>Головне меню</b>\nЩо ти хочеш зробити?",
    },
    "btn.rules": {"de": "📋 Meine Suchen", "en": "📋 My searches",
                  "ru": "📋 Мои поиски", "uk": "📋 Мої пошуки"},
    "btn.new_rule": {"de": "➕ Neue Suche", "en": "➕ New search",
                     "ru": "➕ Новый поиск", "uk": "➕ Новий пошук"},
    "btn.favorites": {"de": "⭐ Favoriten", "en": "⭐ Favorites",
                      "ru": "⭐ Избранное", "uk": "⭐ Обране"},
    "btn.stats": {"de": "📊 Statistik", "en": "📊 Statistics",
                  "ru": "📊 Статистика", "uk": "📊 Статистика"},
    "btn.settings": {"de": "⚙️ Einstellungen", "en": "⚙️ Settings",
                     "ru": "⚙️ Настройки", "uk": "⚙️ Налаштування"},
    "btn.help": {"de": "❓ Hilfe", "en": "❓ Help",
                 "ru": "❓ Помощь", "uk": "❓ Довідка"},
    "btn.back": {"de": "⬅️ Zurück", "en": "⬅️ Back",
                 "ru": "⬅️ Назад", "uk": "⬅️ Назад"},
    "btn.cancel": {"de": "✖️ Abbrechen", "en": "✖️ Cancel",
                   "ru": "✖️ Отмена", "uk": "✖️ Скасувати"},
    "btn.skip": {"de": "⏭ Überspringen", "en": "⏭ Skip",
                 "ru": "⏭ Пропустить", "uk": "⏭ Пропустити"},
    "btn.delete": {"de": "🗑 Löschen", "en": "🗑 Delete",
                   "ru": "🗑 Удалить", "uk": "🗑 Видалити"},
    "btn.toggle": {"de": "⏯ An/Aus", "en": "⏯ On/Off",
                   "ru": "⏯ Вкл/Выкл", "uk": "⏯ Увімк/Вимк"},
    "btn.edit": {"de": "✏️ Bearbeiten", "en": "✏️ Edit",
                 "ru": "✏️ Изменить", "uk": "✏️ Змінити"},
    "edit.menu": {
        "de": "✏️ <b>{name}</b> bearbeiten — was soll geändert werden?",
        "en": "✏️ Edit <b>{name}</b> — what do you want to change?",
        "ru": "✏️ Изменить <b>{name}</b> — что поменять?",
        "uk": "✏️ Змінити <b>{name}</b> — що поміняти?",
    },
    "edit.saved": {
        "de": "✅ Gespeichert!",
        "en": "✅ Saved!",
        "ru": "✅ Сохранено!",
        "uk": "✅ Збережено!",
    },
    "edit.ask_minscore": {
        "de": "🎯 Ab welchem Deal-Score benachrichtigen? (0–100 senden; "
        "0 = jedes neue Angebot, 70 = nur gute Deals)",
        "en": "🎯 Notify from which deal score? (send 0–100; "
        "0 = every new listing, 70 = only good deals)",
        "ru": "🎯 С какого балла уведомлять? (пришли 0–100; "
        "0 = каждое новое объявление, 70 = только выгодные)",
        "uk": "🎯 З якого балу сповіщати? (надішли 0–100; "
        "0 = кожне нове оголошення, 70 = лише вигідні)",
    },
    "rule.ask_name": {
        "de": "Wie soll die Suche heißen? (z. B. <i>RTX 4090 bis 1300€</i>)",
        "en": "Name your search (e.g. <i>RTX 4090 under 1300€</i>)",
        "ru": "Как назвать поиск? (напр. <i>RTX 4090 до 1300€</i>)",
        "uk": "Як назвати пошук? (напр. <i>RTX 4090 до 1300€</i>)",
    },
    "rule.ask_keywords": {
        "de": "🔎 Welche Suchbegriffe? (z. B. <i>rtx 4090</i>)",
        "en": "🔎 Which keywords? (e.g. <i>rtx 4090</i>)",
        "ru": "🔎 Какие ключевые слова? (напр. <i>rtx 4090</i>)",
        "uk": "🔎 Які ключові слова? (напр. <i>rtx 4090</i>)",
    },
    "rule.ask_max_price": {
        "de": "💶 Preis in €?\n"
        "z. B. <code>1200</code> (max), <code>500-1200</code> (von–bis), "
        "<code>ab 500</code> — oder überspringen.\n"
        "💡 Eine Von-Preis-Angabe filtert Zubehör (Hüllen, Kabel) zuverlässig raus!",
        "en": "💶 Price in €?\n"
        "e.g. <code>1200</code> (max), <code>500-1200</code> (range), "
        "<code>ab 500</code> (min) — or skip.\n"
        "💡 A minimum price reliably filters out accessories (cases, cables)!",
        "ru": "💶 Цена в €?\n"
        "напр. <code>1200</code> (макс), <code>500-1200</code> (диапазон), "
        "<code>ab 500</code> (мин) — или пропусти.\n"
        "💡 Минимальная цена надёжно отсеивает аксессуары (чехлы, кабели)!",
        "uk": "💶 Ціна в €?\n"
        "напр. <code>1200</code> (макс), <code>500-1200</code> (діапазон), "
        "<code>ab 500</code> (мін) — або пропусти.\n"
        "💡 Мінімальна ціна надійно відсіює аксесуари (чохли, кабелі)!",
    },
    "rule.ask_category": {
        "de": "📂 In welcher Kategorie suchen?",
        "en": "📂 Which category to search in?",
        "ru": "📂 В какой категории искать?",
        "uk": "📂 У якій категорії шукати?",
    },
    "rule.ask_location": {
        "de": "📍 PLZ oder Ort für die Umkreissuche? (z. B. <code>10115</code> "
        "oder <code>Berlin</code> — gilt für Kleinanzeigen, oder überspringen)",
        "en": "📍 ZIP code or city for radius search? (e.g. <code>10115</code> "
        "or <code>Berlin</code> — applies to Kleinanzeigen, or skip)",
        "ru": "📍 Индекс или город для поиска в радиусе? (напр. <code>10115</code> "
        "или <code>Berlin</code> — для Kleinanzeigen, или пропусти)",
        "uk": "📍 Індекс або місто для пошуку в радіусі? (напр. <code>10115</code> "
        "або <code>Berlin</code> — для Kleinanzeigen, або пропусти)",
    },
    "rule.ask_radius": {
        "de": "📏 Wie weit darf es entfernt sein?",
        "en": "📏 How far away may it be?",
        "ru": "📏 Насколько далеко может быть?",
        "uk": "📏 Наскільки далеко може бути?",
    },
    "btn.all_categories": {"de": "🌐 Alle Kategorien", "en": "🌐 All categories",
                           "ru": "🌐 Все категории", "uk": "🌐 Усі категорії"},
    "rule.ask_exclude": {
        "de": "🚫 Auszuschließende Wörter? Komma-getrennt (oder überspringen)",
        "en": "🚫 Words to exclude? Comma-separated (or skip)",
        "ru": "🚫 Слова-исключения? Через запятую (или пропусти)",
        "uk": "🚫 Слова-виключення? Через кому (або пропусти)",
    },
    "rule.ask_sites": {
        "de": "🏪 Auf welchen Plattformen suchen?\n"
        "Tippe zum An-/Abwählen. Nichts ausgewählt = <b>alle</b>.",
        "en": "🏪 Which platforms to search?\n"
        "Tap to toggle. Nothing selected = <b>all</b>.",
        "ru": "🏪 На каких площадках искать?\n"
        "Нажми для вкл/выкл. Ничего = <b>все</b>.",
        "uk": "🏪 На яких майданчиках шукати?\n"
        "Натисни для увімк/вимк. Нічого = <b>усі</b>.",
    },
    "btn.done": {"de": "✅ Fertig", "en": "✅ Done",
                 "ru": "✅ Готово", "uk": "✅ Готово"},
    "rule.ask_interval": {
        "de": "⏱ Wie oft soll ich für diese Suche prüfen?",
        "en": "⏱ How often should I check for this search?",
        "ru": "⏱ Как часто проверять этот поиск?",
        "uk": "⏱ Як часто перевіряти цей пошук?",
    },
    "btn.all_platforms": {"de": "🌐 Alle", "en": "🌐 All",
                          "ru": "🌐 Все", "uk": "🌐 Усі"},
    "rule.created": {
        "de": "✅ Suche <b>{name}</b> wurde angelegt und ist aktiv!",
        "en": "✅ Search <b>{name}</b> created and active!",
        "ru": "✅ Поиск <b>{name}</b> создан и активен!",
        "uk": "✅ Пошук <b>{name}</b> створено та активовано!",
    },
    "rule.limit_reached": {
        "de": "⚠️ Limit erreicht ({max}). Lösche eine Suche oder upgrade dein Abo.",
        "en": "⚠️ Limit reached ({max}). Delete a search or upgrade your plan.",
        "ru": "⚠️ Достигнут лимит ({max}). Удали поиск или улучши подписку.",
        "uk": "⚠️ Досягнуто ліміту ({max}). Видали пошук або оновіть підписку.",
    },
    "rule.none": {
        "de": "Du hast noch keine Suchen. Tippe auf ➕ Neue Suche.",
        "en": "You have no searches yet. Tap ➕ New search.",
        "ru": "У тебя пока нет поисков. Нажми ➕ Новый поиск.",
        "uk": "У тебе ще немає пошуків. Натисни ➕ Новий пошук.",
    },
    "common.cancelled": {
        "de": "Abgebrochen.", "en": "Cancelled.",
        "ru": "Отменено.", "uk": "Скасовано.",
    },
    "settings.language": {
        "de": "🌐 Sprache wählen:", "en": "🌐 Choose language:",
        "ru": "🌐 Выбери язык:", "uk": "🌐 Обери мову:",
    },
    "settings.language_set": {
        "de": "✅ Sprache auf Deutsch gesetzt.",
        "en": "✅ Language set to English.",
        "ru": "✅ Язык переключён на русский.",
        "uk": "✅ Мову змінено на українську.",
    },
    "help.body": {
        "de": "❓ <b>Hilfe</b>\n\n"
        "• ➕ Neue Suche: Assistent legt eine Suchregel an.\n"
        "• 📋 Meine Suchen: aktivieren/deaktivieren, löschen.\n"
        "• ⭐ Favoriten: gemerkte Angebote.\n"
        "• Ich prüfe deine Suchen automatisch im Intervall und melde neue Deals.",
        "en": "❓ <b>Help</b>\n\n"
        "• ➕ New search: a wizard creates a search rule.\n"
        "• 📋 My searches: enable/disable, delete.\n"
        "• ⭐ Favorites: saved offers.\n"
        "• I check your searches automatically and alert you to new deals.",
        "ru": "❓ <b>Помощь</b>\n\n"
        "• ➕ Новый поиск: мастер создаёт правило.\n"
        "• 📋 Мои поиски: вкл/выкл, удалить.\n"
        "• ⭐ Избранное: сохранённые предложения.\n"
        "• Я проверяю поиски автоматически и присылаю новые находки.",
        "uk": "❓ <b>Довідка</b>\n\n"
        "• ➕ Новий пошук: майстер створює правило.\n"
        "• 📋 Мої пошуки: увімк/вимк, видалити.\n"
        "• ⭐ Обране: збережені пропозиції.\n"
        "• Я перевіряю пошуки автоматично та надсилаю нові знахідки.",
    },
}


def t(key: str, lang: str | None = None, /, **kwargs: object) -> str:
    """Translate ``key`` into ``lang`` with optional ``str.format`` kwargs."""
    lang = lang if lang in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE
    entry = _TEXTS.get(key, {})
    template = entry.get(lang) or entry.get(DEFAULT_LANGUAGE) or key
    if kwargs:
        try:
            return template.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return template
    return template
