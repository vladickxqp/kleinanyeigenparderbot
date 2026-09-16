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
        "<b>Suchen</b>\n"
        "• ➕ Neue Suche: Assistent (Kategorie, Preis, Ort, Intervall)\n"
        "• 📋 Meine Suchen: ▶️ sofort suchen, ✏️ bearbeiten, ⏯ an/aus\n"
        "• /suche begriff — Schnell-Suche ohne Regel\n\n"
        "<b>Premium</b>\n"
        "• /premium — Vorteile &amp; Upgrade · /trial — gratis testen\n"
        "• /coupon CODE — Gutschein · /ref — Freunde werben\n\n"
        "<b>Sonstiges</b>\n"
        "• /status — läuft alles? · 🌙 Ruhezeiten in ⚙️ Einstellungen\n"
        "• 📸 Produktfoto senden → Marktwert-Schätzung (💎 Premium)\n"
        "• Ich prüfe deine Suchen automatisch und melde nur echte Neuheiten "
        "(inkl. 📉 Preisstürzen).",
        "en": "❓ <b>Help</b>\n\n"
        "<b>Searches</b>\n"
        "• ➕ New search: wizard (category, price, location, interval)\n"
        "• 📋 My searches: ▶️ run now, ✏️ edit, ⏯ on/off\n"
        "• /suche term — quick search without a rule\n\n"
        "<b>Premium</b>\n"
        "• /premium — perks &amp; upgrade · /trial — free trial\n"
        "• /coupon CODE — voucher · /ref — invite friends\n\n"
        "<b>Other</b>\n"
        "• /status — is everything running? · 🌙 quiet hours in ⚙️ settings\n"
        "• 📸 send a product photo → value estimate (💎 Premium)\n"
        "• I check your searches automatically and only alert on true news "
        "(incl. 📉 price drops).",
        "ru": "❓ <b>Помощь</b>\n\n"
        "<b>Поиски</b>\n"
        "• ➕ Новый поиск: мастер (категория, цена, место, интервал)\n"
        "• 📋 Мои поиски: ▶️ искать сейчас, ✏️ изменить, ⏯ вкл/выкл\n"
        "• /suche запрос — быстрый поиск без правила\n\n"
        "<b>Премиум</b>\n"
        "• /premium — преимущества · /trial — бесплатный тест\n"
        "• /coupon CODE — купон · /ref — пригласить друзей\n\n"
        "<b>Прочее</b>\n"
        "• /status — всё ли работает? · 🌙 тихие часы в ⚙️ настройках\n"
        "• 📸 пришли фото товара → оценка стоимости (💎 Премиум)\n"
        "• Я проверяю поиски автоматически и присылаю только настоящие "
        "новинки (включая 📉 падения цен).",
        "uk": "❓ <b>Довідка</b>\n\n"
        "<b>Пошуки</b>\n"
        "• ➕ Новий пошук: майстер (категорія, ціна, місце, інтервал)\n"
        "• 📋 Мої пошуки: ▶️ шукати зараз, ✏️ змінити, ⏯ увімк/вимк\n"
        "• /suche запит — швидкий пошук без правила\n\n"
        "<b>Преміум</b>\n"
        "• /premium — переваги · /trial — безкоштовний тест\n"
        "• /coupon CODE — купон · /ref — запросити друзів\n\n"
        "<b>Інше</b>\n"
        "• /status — чи все працює? · 🌙 тихі години в ⚙️ налаштуваннях\n"
        "• 📸 надішли фото товару → оцінка вартості (💎 Преміум)\n"
        "• Я перевіряю пошуки автоматично та надсилаю лише справжні "
        "новинки (включно з 📉 падінням цін).",
    },
    # --- Deal card ---------------------------------------------------------
    "card.verdict.steal": {"de": "🔥 <b>KRACHER</b>", "en": "🔥 <b>STEAL</b>",
                           "ru": "🔥 <b>ОГОНЬ</b>", "uk": "🔥 <b>ВОГОНЬ</b>"},
    "card.verdict.great": {"de": "💚 <b>Top-Deal</b>", "en": "💚 <b>Top deal</b>",
                           "ru": "💚 <b>Отличная цена</b>", "uk": "💚 <b>Чудова ціна</b>"},
    "card.verdict.good": {"de": "✅ <b>Guter Deal</b>", "en": "✅ <b>Good deal</b>",
                          "ru": "✅ <b>Хорошая цена</b>", "uk": "✅ <b>Добра ціна</b>"},
    "card.verdict.fair": {"de": "⚖️ Fairer Preis", "en": "⚖️ Fair price",
                          "ru": "⚖️ Справедливая цена", "uk": "⚖️ Справедлива ціна"},
    "card.verdict.overpriced": {"de": "🔴 Überteuert", "en": "🔴 Overpriced",
                                "ru": "🔴 Цена завышена", "uk": "🔴 Ціна завищена"},
    "card.verdict.unknown": {"de": "❔ Unbewertet", "en": "❔ Unrated",
                             "ru": "❔ Без оценки", "uk": "❔ Без оцінки"},
    "card.negotiable": {"de": "VB", "en": "or best offer",
                        "ru": "торг", "uk": "торг"},
    "card.shipping_cost": {"de": "+ {amount} Versand", "en": "+ {amount} shipping",
                           "ru": "+ {amount} доставка", "uk": "+ {amount} доставка"},
    "card.shipping_possible": {"de": "📦 Versand möglich", "en": "📦 Shipping available",
                               "ru": "📦 Есть доставка", "uk": "📦 Є доставка"},
    "card.price_drop": {"de": "📉 <b>PREISSTURZ:</b> {before} → {now} (−{saved})",
                        "en": "📉 <b>PRICE DROP:</b> {before} → {now} (−{saved})",
                        "ru": "📉 <b>ЦЕНА УПАЛА:</b> {before} → {now} (−{saved})",
                        "uk": "📉 <b>ЦІНА ВПАЛА:</b> {before} → {now} (−{saved})"},
    "card.market_price": {"de": "📈 Marktpreis ~ {amount}", "en": "📈 Market price ~ {amount}",
                          "ru": "📈 Рыночная цена ~ {amount}", "uk": "📈 Ринкова ціна ~ {amount}"},
    "card.below_market": {"de": "💰 {percent}% unter Markt{saving}",
                          "en": "💰 {percent}% below market{saving}",
                          "ru": "💰 На {percent}% ниже рынка{saving}",
                          "uk": "💰 На {percent}% нижче ринку{saving}"},
    "card.auction": {"de": "🔨 Auktion", "en": "🔨 Auction",
                     "ru": "🔨 Аукцион", "uk": "🔨 Аукціон"},
    "card.flip": {"de": "♻️ <b>Flip:</b> Kauf {buy} → Markt {market} = "
                        "<b>{net} netto</b> nach Gebühren (ROI {roi}%)",
                  "en": "♻️ <b>Flip:</b> buy {buy} → market {market} = "
                        "<b>{net} net</b> after fees (ROI {roi}%)",
                  "ru": "♻️ <b>Перепродажа:</b> покупка {buy} → рынок {market} = "
                        "<b>{net} чистыми</b> после комиссий (ROI {roi}%)",
                  "uk": "♻️ <b>Перепродаж:</b> купівля {buy} → ринок {market} = "
                        "<b>{net} чистими</b> після комісій (ROI {roi}%)"},

    # --- Premium -----------------------------------------------------------
    "premium.title": {"de": "💎 <b>Deal Hunter Premium</b>",
                      "en": "💎 <b>Deal Hunter Premium</b>",
                      "ru": "💎 <b>Deal Hunter Премиум</b>",
                      "uk": "💎 <b>Deal Hunter Преміум</b>"},
    "premium.free_line": {
        "de": "Free: {rules} Suchen, Prüfung alle {minutes} Minuten.",
        "en": "Free: {rules} searches, checked every {minutes} minutes.",
        "ru": "Free: {rules} поиска, проверка каждые {minutes} минут.",
        "uk": "Free: {rules} пошуки, перевірка кожні {minutes} хвилин.",
    },
    "premium.plan_rules_unlimited": {"de": "unbegrenzte Suchen", "en": "unlimited searches",
                                     "ru": "безлимитные поиски", "uk": "безлімітні пошуки"},
    "premium.plan_rules": {"de": "{count} Suchen", "en": "{count} searches",
                           "ru": "{count} поисков", "uk": "{count} пошуків"},
    "premium.plan_line": {
        "de": "   {rules}, Prüfung ab {minutes} min, Prioritäts-Verarbeitung{extra}",
        "en": "   {rules}, checks from {minutes} min, priority processing{extra}",
        "ru": "   {rules}, проверка от {minutes} мин, приоритетная обработка{extra}",
        "uk": "   {rules}, перевірка від {minutes} хв, пріоритетна обробка{extra}",
    },
    "premium.plan_extra_photo": {"de": ", Foto-Bewertung", "en": ", photo valuation",
                                 "ru": ", оценка по фото", "uk": ", оцінка за фото"},
    "premium.cancel_anytime": {
        "de": "Jederzeit kündbar, direkt hier im Chat.",
        "en": "Cancel any time, right here in the chat.",
        "ru": "Отменить можно в любой момент прямо здесь.",
        "uk": "Скасувати можна будь-коли просто тут.",
    },
    "premium.try_free": {"de": "🆓 Kostenlos testen: /trial ({days} Tage)",
                         "en": "🆓 Try it free: /trial ({days} days)",
                         "ru": "🆓 Бесплатный тест: /trial ({days} дней)",
                         "uk": "🆓 Безкоштовний тест: /trial ({days} днів)"},
    "premium.coupon_hint": {"de": "🎟 Gutschein? /coupon CODE", "en": "🎟 Got a coupon? /coupon CODE",
                            "ru": "🎟 Есть купон? /coupon CODE", "uk": "🎟 Є купон? /coupon CODE"},
    "premium.referral_hint": {"de": "🎫 Freunde werben, Gratis-Tage kassieren: /ref",
                              "en": "🎫 Invite friends, collect free days: /ref",
                              "ru": "🎫 Приглашай друзей и получай бесплатные дни: /ref",
                              "uk": "🎫 Запрошуй друзів і отримуй безкоштовні дні: /ref"},
    "premium.btn_buy": {"de": "💳 {plan} — {stars} ⭐/Monat", "en": "💳 {plan} — {stars} ⭐/month",
                        "ru": "💳 {plan} — {stars} ⭐/мес", "uk": "💳 {plan} — {stars} ⭐/міс"},
    "premium.btn_history": {"de": "📜 Zahlungsverlauf", "en": "📜 Payment history",
                            "ru": "📜 История платежей", "uk": "📜 Історія платежів"},
    "premium.btn_cancel": {"de": "❌ Abo kündigen", "en": "❌ Cancel subscription",
                           "ru": "❌ Отменить подписку", "uk": "❌ Скасувати підписку"},
    "premium.active": {
        "de": "💎 <b>Premium ist aktiv</b>",
        "en": "💎 <b>Premium is active</b>",
        "ru": "💎 <b>Премиум активен</b>",
        "uk": "💎 <b>Преміум активний</b>",
    },
    "premium.active_until": {
        "de": "✅ Aktiv bis: <b>{date}</b>",
        "en": "✅ Active until: <b>{date}</b>",
        "ru": "✅ Активен до: <b>{date}</b>",
        "uk": "✅ Активний до: <b>{date}</b>",
    },

    # --- Level comparison --------------------------------------------------
    "premium.compare_title": {
        "de": "📊 <b>Die vier Stufen im Vergleich</b>",
        "en": "📊 <b>The four levels side by side</b>",
        "ru": "📊 <b>Четыре уровня — сравнение</b>",
        "uk": "📊 <b>Чотири рівні — порівняння</b>",
    },
    "premium.compare_current": {
        "de": "  ← deine Stufe",
        "en": "  ← your level",
        "ru": "  ← твой уровень",
        "uk": "  ← твій рівень",
    },
    "premium.compare_free_price": {
        "de": "kostenlos", "en": "free of charge",
        "ru": "бесплатно", "uk": "безкоштовно",
    },
    "premium.compare_price": {
        "de": "{stars} ⭐ (~{eur} €)/Monat",
        "en": "{stars} ⭐ (~{eur} €)/month",
        "ru": "{stars} ⭐ (~{eur} €)/мес",
        "uk": "{stars} ⭐ (~{eur} €)/міс",
    },
    "premium.compare_searches": {
        "de": "• Suchen: <b>{rules}</b> · Prüfung alle {minutes} Min",
        "en": "• Searches: <b>{rules}</b> · checked every {minutes} min",
        "ru": "• Поиски: <b>{rules}</b> · проверка каждые {minutes} мин",
        "uk": "• Пошуки: <b>{rules}</b> · перевірка кожні {minutes} хв",
    },
    "premium.compare_fast": {
        "de": "• Schnell-Slots: <b>{slots}</b> ab {minutes} Min",
        "en": "• Fast slots: <b>{slots}</b> from {minutes} min",
        "ru": "• Быстрые слоты: <b>{slots}</b> от {minutes} мин",
        "uk": "• Швидкі слоти: <b>{slots}</b> від {minutes} хв",
    },
    "premium.compare_fast_none": {
        "de": "• Keine Schnell-Slots",
        "en": "• No fast slots",
        "ru": "• Без быстрых слотов",
        "uk": "• Без швидких слотів",
    },
    "premium.compare_cards": {
        "de": "• Karten: <b>{cards}</b> · Foto-Bewertungen: {photos}",
        "en": "• Cards: <b>{cards}</b> · photo valuations: {photos}",
        "ru": "• Карточки: <b>{cards}</b> · оценок по фото: {photos}",
        "uk": "• Картки: <b>{cards}</b> · оцінок за фото: {photos}",
    },
    "premium.compare_quick": {
        "de": "• Schnell-Suchen: {quick} · Verlauf: {history}",
        "en": "• Quick searches: {quick} · history: {history}",
        "ru": "• Быстрые поиски: {quick} · история: {history}",
        "uk": "• Швидкі пошуки: {quick} · історія: {history}",
    },
    "premium.compare_adds": {
        "de": "• Neu ab hier: {features}",
        "en": "• New from here: {features}",
        "ru": "• Новое с этого уровня: {features}",
        "uk": "• Нове з цього рівня: {features}",
    },
    "premium.not_bookable": {
        "de": "ℹ️ <b>{plan}</b> ist gerade nicht buchbar: die Stufe braucht einen "
        "Proxy-Pool, und der steht noch nicht bereit.",
        "en": "ℹ️ <b>{plan}</b> is not on sale right now: the level needs a proxy "
        "pool and that is not ready yet.",
        "ru": "ℹ️ <b>{plan}</b> сейчас не купить: уровню нужен пул прокси, а он "
        "ещё не готов.",
        "uk": "ℹ️ <b>{plan}</b> зараз не придбати: рівню потрібен пул проксі, а він "
        "ще не готовий.",
    },
    "premium.not_bookable_short": {
        "de": "Nicht buchbar: Proxy-Pool fehlt.",
        "en": "Not on sale: proxy pool missing.",
        "ru": "Не продаётся: нет пула прокси.",
        "uk": "Не продається: немає пулу проксі.",
    },
    "premium.feature.flip_mode": {
        "de": "Flip-Modus", "en": "Flip mode",
        "ru": "Режим перепродажи", "uk": "Режим перепродажу",
    },
    "premium.feature.rule_power": {
        "de": "Profi-Filter", "en": "Power filters",
        "ru": "Профи-фильтры", "uk": "Профі-фільтри",
    },
    "premium.feature.export": {
        "de": "Export", "en": "Export", "ru": "Экспорт", "uk": "Експорт",
    },
    "premium.feature.market_report": {
        "de": "Marktbericht", "en": "Market report",
        "ru": "Отчёт по рынку", "uk": "Звіт по ринку",
    },
    "premium.feature.forwarding": {
        "de": "Weiterleitung in Kanäle", "en": "Forwarding to channels",
        "ru": "Пересылка в каналы", "uk": "Пересилання в канали",
    },

    # --- Usage (/usage) ----------------------------------------------------
    "usage.title": {
        "de": "📈 <b>Dein Verbrauch</b>",
        "en": "📈 <b>Your usage</b>",
        "ru": "📈 <b>Твой расход</b>",
        "uk": "📈 <b>Твоя витрата</b>",
    },
    "usage.level": {
        "de": "Stufe: <b>{label}</b>",
        "en": "Level: <b>{label}</b>",
        "ru": "Уровень: <b>{label}</b>",
        "uk": "Рівень: <b>{label}</b>",
    },
    "usage.kind.cards": {
        "de": "Deal-Karten", "en": "Deal cards",
        "ru": "Карточки сделок", "uk": "Картки угод",
    },
    "usage.kind.photo": {
        "de": "Foto-Bewertungen", "en": "Photo valuations",
        "ru": "Оценки по фото", "uk": "Оцінки за фото",
    },
    "usage.kind.quick": {
        "de": "Schnell-Suchen", "en": "Quick searches",
        "ru": "Быстрые поиски", "uk": "Швидкі пошуки",
    },
    "usage.kind.nego": {
        "de": "Verhandlungen", "en": "Negotiations",
        "ru": "Переговоры", "uk": "Перемовини",
    },
    "usage.row_head": {
        "de": "<b>{name}</b> {window}",
        "en": "<b>{name}</b> {window}",
        "ru": "<b>{name}</b> {window}",
        "uk": "<b>{name}</b> {window}",
    },
    "usage.row_capped": {
        "de": "{bar} {used}/{limit} · {remaining} übrig",
        "en": "{bar} {used}/{limit} · {remaining} left",
        "ru": "{bar} {used}/{limit} · осталось {remaining}",
        "uk": "{bar} {used}/{limit} · залишилось {remaining}",
    },
    "usage.row_exhausted": {
        "de": "{bar} {used}/{limit} · aufgebraucht",
        "en": "{bar} {used}/{limit} · used up",
        "ru": "{bar} {used}/{limit} · исчерпано",
        "uk": "{bar} {used}/{limit} · вичерпано",
    },
    "usage.row_unlimited": {
        "de": "unbegrenzt · {used} genutzt",
        "en": "unlimited · {used} used",
        "ru": "без лимита · использовано {used}",
        "uk": "без ліміту · використано {used}",
    },
    "usage.fast_title": {
        "de": "⚡ <b>Schnell-Slots</b> ({used}/{total})",
        "en": "⚡ <b>Fast slots</b> ({used}/{total})",
        "ru": "⚡ <b>Быстрые слоты</b> ({used}/{total})",
        "uk": "⚡ <b>Швидкі слоти</b> ({used}/{total})",
    },
    "usage.fast_row": {
        "de": "• {name} — alle {minutes} Min",
        "en": "• {name} — every {minutes} min",
        "ru": "• {name} — каждые {minutes} мин",
        "uk": "• {name} — кожні {minutes} хв",
    },
    "usage.fast_none": {
        "de": "Gerade belegt keine Suche einen Schnell-Slot.",
        "en": "No search is holding a fast slot right now.",
        "ru": "Сейчас ни один поиск не занимает быстрый слот.",
        "uk": "Зараз жоден пошук не займає швидкий слот.",
    },
    "usage.fast_locked": {
        "de": "⚡ Deine Stufe hat keine Schnell-Slots.",
        "en": "⚡ Your level has no fast slots.",
        "ru": "⚡ На твоём уровне нет быстрых слотов.",
        "uk": "⚡ На твоєму рівні немає швидких слотів.",
    },
    "usage.upgrade": {
        "de": "⬆️ <b>Nächste Stufe</b>\n{hint}",
        "en": "⬆️ <b>Next level</b>\n{hint}",
        "ru": "⬆️ <b>Следующий уровень</b>\n{hint}",
        "uk": "⬆️ <b>Наступний рівень</b>\n{hint}",
    },
    "usage.top_level": {
        "de": "🏆 Du bist auf der höchsten Stufe — mehr geht nicht.",
        "en": "🏆 You are on the top level — there is nothing above.",
        "ru": "🏆 Ты на высшем уровне — выше некуда.",
        "uk": "🏆 Ти на найвищому рівні — вище нікуди.",
    },
    "btn.usage": {"de": "📈 Verbrauch", "en": "📈 Usage",
                  "ru": "📈 Расход", "uk": "📈 Витрата"},
    "btn.premium": {"de": "💎 Premium", "en": "💎 Premium",
                    "ru": "💎 Премиум", "uk": "💎 Преміум"},

    # --- Privacy / data ----------------------------------------------------
    "privacy.commands": {
        "de": "🔐 Deine Daten: /privacy · Export: /meinedaten · Löschen: /loeschen",
        "en": "🔐 Your data: /privacy · Export: /meinedaten · Delete: /loeschen",
        "ru": "🔐 Твои данные: /privacy · Выгрузка: /meinedaten · Удалить: /loeschen",
        "uk": "🔐 Твої дані: /privacy · Вивантаження: /meinedaten · Видалити: /loeschen",
    },
}


def feature_label(key: str, lang: str | None = None) -> str:
    """Name of a tier feature flag. A flag added in settings but not yet
    translated shows its raw key instead of a broken lookup string."""
    label = t(f"premium.feature.{key}", lang)
    return key if label.startswith("premium.feature.") else label


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
