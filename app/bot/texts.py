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
    # --- Rule card and edit menu: the screen a user looks at most ----------
    "rule.state_active": {
        "de": "🟢 aktiv", "en": "🟢 active", "ru": "🟢 активен", "uk": "🟢 активний",
    },
    "rule.state_paused": {
        "de": "⚪️ pausiert", "en": "⚪️ paused",
        "ru": "⚪️ на паузе", "uk": "⚪️ на паузі",
    },
    "rule.f_category": {
        "de": "Kategorie", "en": "Category", "ru": "Категория", "uk": "Категорія",
    },
    "rule.f_sites": {
        "de": "Plattformen", "en": "Marketplaces",
        "ru": "Площадки", "uk": "Майданчики",
    },
    "rule.f_interval": {
        "de": "Intervall", "en": "Interval", "ru": "Интервал", "uk": "Інтервал",
    },
    "rule.f_minscore": {
        "de": "Min. Deal-Score", "en": "Min. deal score",
        "ru": "Мин. балл сделки", "uk": "Мін. бал угоди",
    },
    "rule.f_vehicle": {"de": "Auto", "en": "Car", "ru": "Авто", "uk": "Авто"},
    "rule.f_all": {"de": "alle", "en": "all", "ru": "все", "uk": "усі"},
    "rule.f_none": {"de": "—", "en": "—", "ru": "—", "uk": "—"},
    # --- Values a filter can hold -----------------------------------------
    "val.cond.any": {"de": "egal", "en": "any", "ru": "любое", "uk": "будь-який"},
    "val.cond.new": {"de": "neu", "en": "new", "ru": "новое", "uk": "новий"},
    "val.cond.used": {"de": "gebraucht", "en": "used", "ru": "б/у", "uk": "вживаний"},
    "val.cond.defective": {
        "de": "defekt", "en": "faulty", "ru": "неисправное", "uk": "несправний",
    },
    "val.cond.like_new": {
        "de": "wie neu", "en": "like new", "ru": "как новое", "uk": "як новий",
    },
    "val.cond.refurbished": {
        "de": "refurbished", "en": "refurbished",
        "ru": "восстановленное", "uk": "відновлений",
    },
    "val.ship.any": {"de": "egal", "en": "any", "ru": "любая", "uk": "будь-яка"},
    "val.ship.yes": {
        "de": "mit Versand", "en": "with shipping",
        "ru": "с доставкой", "uk": "з доставкою",
    },
    "val.ship.no": {
        "de": "nur Abholung", "en": "pickup only",
        "ru": "только самовывоз", "uk": "лише самовивіз",
    },
    "val.auction.on": {"de": "an", "en": "on", "ru": "вкл", "uk": "увімк"},
    "val.auction.off": {"de": "aus", "en": "off", "ru": "выкл", "uk": "вимк"},
    "val.price_upto": {
        "de": "bis {amount}", "en": "up to {amount}",
        "ru": "до {amount}", "uk": "до {amount}",
    },
    "val.price_from": {
        "de": "ab {amount}", "en": "from {amount}",
        "ru": "от {amount}", "uk": "від {amount}",
    },
    "val.km_upto": {
        "de": "bis {km} km", "en": "up to {km} km",
        "ru": "до {km} км", "uk": "до {km} км",
    },
    "val.year_from": {
        "de": "ab {year}", "en": "from {year}", "ru": "от {year}", "uk": "від {year}",
    },
    # --- Edit-menu buttons ------------------------------------------------
    "btn.edit_name": {"de": "📝 Name", "en": "📝 Name", "ru": "📝 Название",
                      "uk": "📝 Назва"},
    "btn.edit_keywords": {"de": "🔎 Suchwörter", "en": "🔎 Keywords",
                          "ru": "🔎 Ключевые слова", "uk": "🔎 Ключові слова"},
    "btn.edit_category": {"de": "📂 Kategorie", "en": "📂 Category",
                          "ru": "📂 Категория", "uk": "📂 Категорія"},
    "btn.edit_price": {"de": "💶 Preis", "en": "💶 Price", "ru": "💶 Цена",
                       "uk": "💶 Ціна"},
    "btn.edit_exclude": {"de": "🚫 Ausschluss", "en": "🚫 Exclude",
                         "ru": "🚫 Исключить", "uk": "🚫 Виключити"},
    "btn.edit_location": {"de": "📍 Ort", "en": "📍 Location", "ru": "📍 Место",
                          "uk": "📍 Місце"},
    "btn.edit_interval": {"de": "⏱ Intervall", "en": "⏱ Interval",
                          "ru": "⏱ Интервал", "uk": "⏱ Інтервал"},
    "btn.edit_minscore": {"de": "🎯 Min-Score", "en": "🎯 Min score",
                          "ru": "🎯 Мин. балл", "uk": "🎯 Мін. бал"},
    "btn.edit_vehicle": {"de": "🚗 Auto: {value}", "en": "🚗 Car: {value}",
                         "ru": "🚗 Авто: {value}", "uk": "🚗 Авто: {value}"},
    "btn.edit_condition": {"de": "🏷 Zustand: {value}", "en": "🏷 Condition: {value}",
                           "ru": "🏷 Состояние: {value}", "uk": "🏷 Стан: {value}"},
    "btn.edit_shipping": {"de": "📦 Versand: {value}", "en": "📦 Shipping: {value}",
                          "ru": "📦 Доставка: {value}", "uk": "📦 Доставка: {value}"},
    "btn.edit_auctions": {"de": "🔨 Auktionen: {value}", "en": "🔨 Auctions: {value}",
                          "ru": "🔨 Аукционы: {value}", "uk": "🔨 Аукціони: {value}"},
    "btn.edit_locked": {
        "de": "🔒 Zustand · Versand · Auktionen",
        "en": "🔒 Condition · Shipping · Auctions",
        "ru": "🔒 Состояние · Доставка · Аукционы",
        "uk": "🔒 Стан · Доставка · Аукціони",
    },
    # --- Wizard choices ---------------------------------------------------
    "choice.cat.handys": {"de": "📱 Handys", "en": "📱 Phones",
                          "ru": "📱 Телефоны", "uk": "📱 Телефони"},
    "choice.cat.notebooks": {"de": "💻 Notebooks", "en": "💻 Laptops",
                             "ru": "💻 Ноутбуки", "uk": "💻 Ноутбуки"},
    "choice.cat.pcs": {"de": "🖥 PCs", "en": "🖥 PCs", "ru": "🖥 ПК", "uk": "🖥 ПК"},
    "choice.cat.pc-zubehoer": {"de": "🎮 GPU / PC-Teile", "en": "🎮 GPU / PC parts",
                               "ru": "🎮 Видеокарты / комплектующие",
                               "uk": "🎮 Відеокарти / комплектуючі"},
    "choice.cat.konsolen": {"de": "🕹 Konsolen", "en": "🕹 Consoles",
                            "ru": "🕹 Консоли", "uk": "🕹 Консолі"},
    "choice.cat.elektronik": {"de": "🔌 Elektronik", "en": "🔌 Electronics",
                              "ru": "🔌 Электроника", "uk": "🔌 Електроніка"},
    "choice.cat.autos": {"de": "🚗 Autos", "en": "🚗 Cars",
                         "ru": "🚗 Автомобили", "uk": "🚗 Автомобілі"},
    "choice.cat.fahrraeder": {"de": "🚲 Fahrräder", "en": "🚲 Bicycles",
                              "ru": "🚲 Велосипеды", "uk": "🚲 Велосипеди"},
    "choice.cond.any": {"de": "🔀 Egal", "en": "🔀 Any",
                        "ru": "🔀 Любое", "uk": "🔀 Будь-який"},
    "choice.cond.new": {"de": "✨ Neu / OVP", "en": "✨ New / sealed",
                        "ru": "✨ Новое / запечатано", "uk": "✨ Новий / запечатаний"},
    "choice.cond.used": {"de": "📦 Gebraucht", "en": "📦 Used",
                         "ru": "📦 Б/у", "uk": "📦 Вживаний"},
    "choice.cond.defective": {"de": "🔧 Defekt / Bastler", "en": "🔧 Faulty / for parts",
                              "ru": "🔧 Неисправное / на запчасти",
                              "uk": "🔧 Несправний / на запчастини"},
    "choice.ship.any": {"de": "🔀 Egal", "en": "🔀 Any",
                        "ru": "🔀 Любая", "uk": "🔀 Будь-яка"},
    "choice.ship.yes": {"de": "📦 Nur mit Versand", "en": "📦 Shipping only",
                        "ru": "📦 Только с доставкой", "uk": "📦 Лише з доставкою"},
    "choice.ship.no": {"de": "🚗 Nur Abholung", "en": "🚗 Pickup only",
                       "ru": "🚗 Только самовывоз", "uk": "🚗 Лише самовивіз"},
    "choice.auction.keep": {"de": "🔨 Auktionen zeigen", "en": "🔨 Show auctions",
                            "ru": "🔨 Показывать аукционы",
                            "uk": "🔨 Показувати аукціони"},
    "choice.auction.hide": {"de": "🚫 Auktionen ausblenden", "en": "🚫 Hide auctions",
                            "ru": "🚫 Скрыть аукционы", "uk": "🚫 Сховати аукціони"},
    # --- How many marketplaces one rule may search -------------------------
    "rule.sites_capped": {
        "de": "🔒 In deinem Tarif sucht eine Regel auf <b>einer</b> Plattform. "
        "Mit {level} durchsuchst du alle gleichzeitig — dieselbe Suche, "
        "mehr Treffer. → /premium",
        "en": "🔒 On your plan a search runs on <b>one</b> marketplace. With "
        "{level} you search them all at once — same search, more hits. "
        "→ /premium",
        "ru": "🔒 На твоём тарифе поиск идёт по <b>одной</b> площадке. С {level} "
        "ты ищешь сразу по всем — тот же поиск, больше находок. → /premium",
        "uk": "🔒 На твоєму тарифі пошук іде по <b>одному</b> майданчику. З "
        "{level} ти шукаєш одразу по всіх — той самий пошук, більше знахідок. "
        "→ /premium",
    },
    "rule.sites_locked": {
        "de": "🔒 Eine Plattform pro Suche in deinem Tarif. Mit {level} alle "
        "gleichzeitig — /premium",
        "en": "🔒 One marketplace per search on your plan. {level} searches "
        "them all at once — /premium",
        "ru": "🔒 Одна площадка на поиск в твоём тарифе. {level} ищет по всем "
        "сразу — /premium",
        "uk": "🔒 Один майданчик на пошук у твоєму тарифі. {level} шукає по "
        "всіх одразу — /premium",
    },
    "rule.sites_all_capped": {
        "de": "🔒 {site} ist gesetzt — mehr als eine Plattform gibt es ab {level}.",
        "en": "🔒 {site} it is — more than one marketplace comes with {level}.",
        "ru": "🔒 Выбрано: {site} — больше одной площадки доступно с {level}.",
        "uk": "🔒 Обрано: {site} — більше одного майданчика доступно з {level}.",
    },
    "rule.f_sites_more": {
        "de": " · +{count} mit {level}", "en": " · +{count} with {level}",
        "ru": " · +{count} с {level}", "uk": " · +{count} з {level}",
    },
    # --- Menu and action buttons -------------------------------------------
    "btn.premium": {"de": "💎 Premium", "en": "💎 Premium",
                    "ru": "💎 Премиум", "uk": "💎 Преміум"},
    "btn.support": {"de": "💬 Support", "en": "💬 Support",
                    "ru": "💬 Поддержка", "uk": "💬 Підтримка"},
    "btn.flips": {"de": "📦 Meine Flips", "en": "📦 My flips",
                  "ru": "📦 Мои перепродажи", "uk": "📦 Мої перепродажі"},
    "btn.open_app": {"de": "🌐 App öffnen", "en": "🌐 Open app",
                     "ru": "🌐 Открыть приложение", "uk": "🌐 Відкрити застосунок"},
    "btn.run_now": {"de": "▶️ Jetzt suchen", "en": "▶️ Search now",
                    "ru": "▶️ Искать сейчас", "uk": "▶️ Шукати зараз"},
    "btn.open_link": {"de": "🔗 Öffnen", "en": "🔗 Open",
                      "ru": "🔗 Открыть", "uk": "🔗 Відкрити"},
    "btn.track_price": {"de": "👁 Preis", "en": "👁 Price",
                        "ru": "👁 Цена", "uk": "👁 Ціна"},
    "btn.bought_flip": {
        "de": "🛒 Gekauft — Flip tracken", "en": "🛒 Bought — track this flip",
        "ru": "🛒 Куплено — отслеживать", "uk": "🛒 Куплено — відстежувати",
    },
    # --- Running a rule ----------------------------------------------------
    "rule.toggled_active": {"de": "🟢 Aktiv", "en": "🟢 Active",
                            "ru": "🟢 Активен", "uk": "🟢 Активний"},
    "rule.toggled_paused": {"de": "⚪️ Pausiert", "en": "⚪️ Paused",
                            "ru": "⚪️ На паузе", "uk": "⚪️ На паузі"},
    "rule.deleted": {"de": "🗑 Gelöscht", "en": "🗑 Deleted",
                     "ru": "🗑 Удалено", "uk": "🗑 Видалено"},
    "rule.stats_head": {
        "de": "📊 Letzte 7 Tage", "en": "📊 Last 7 days",
        "ru": "📊 Последние 7 дней", "uk": "📊 Останні 7 днів",
    },
    "rule.stats_empty": {
        "de": "noch keine Treffer", "en": "no hits yet",
        "ru": "пока ничего", "uk": "поки нічого",
    },
    "rule.stats_offers": {
        "de": "{count} Angebote", "en": "{count} listings",
        "ru": "{count} объявлений", "uk": "{count} оголошень",
    },
    "rule.run_started": {"de": "🔍 Suche läuft…", "en": "🔍 Searching…",
                         "ru": "🔍 Ищу…", "uk": "🔍 Шукаю…"},
    "rule.run_working": {
        "de": "🔍 Suche läuft, einen Moment…", "en": "🔍 Searching, one moment…",
        "ru": "🔍 Ищу, один момент…", "uk": "🔍 Шукаю, один момент…",
    },
    "rule.run_failed": {
        "de": "⚠️ Suche fehlgeschlagen:\n<code>{detail}</code>\n\n"
        "Bitte diese Meldung an den Entwickler weitergeben.",
        "en": "⚠️ Search failed:\n<code>{detail}</code>\n\n"
        "Please pass this message on to the developer.",
        "ru": "⚠️ Поиск не удался:\n<code>{detail}</code>\n\n"
        "Передай это сообщение разработчику.",
        "uk": "⚠️ Пошук не вдався:\n<code>{detail}</code>\n\n"
        "Передай це повідомлення розробнику.",
    },
    "rule.run_done": {
        "de": "✅ Fertig: <b>{found}</b> neue Treffer, {sent} Karte(n) gesendet.",
        "en": "✅ Done: <b>{found}</b> new hits, {sent} card(s) sent.",
        "ru": "✅ Готово: <b>{found}</b> новых находок, отправлено карточек: {sent}.",
        "uk": "✅ Готово: <b>{found}</b> нових знахідок, надіслано карток: {sent}.",
    },
    "rule.run_empty": {
        "de": "😕 Keine neuen Treffer. Entweder gibt es nichts Neues, oder die "
        "Filter sind zu streng (Preis/Ausschlusswörter prüfen).",
        "en": "😕 No new hits. Either nothing new turned up, or the filters are "
        "too tight (check price and exclude words).",
        "ru": "😕 Новых находок нет. Либо ничего нового, либо фильтры слишком "
        "строгие (проверь цену и слова-исключения).",
        "uk": "😕 Нових знахідок немає. Або нічого нового, або фільтри надто "
        "суворі (перевір ціну та слова-винятки).",
    },
    "rule.run_capped": {
        "de": "\n🔒 Tageslimit für Karten erreicht.",
        "en": "\n🔒 Daily card limit reached.",
        "ru": "\n🔒 Дневной лимит карточек исчерпан.",
        "uk": "\n🔒 Денний ліміт карток вичерпано.",
    },
    "rule.run_capped_hint": {
        "de": " Mehr davon: {hint}", "en": " More of them: {hint}",
        "ru": " Больше: {hint}", "uk": " Більше: {hint}",
    },
    "rule.run_cooldown": {
        "de": "⏳ Bitte {seconds}s warten (Schutz vor Sperren).",
        "en": "⏳ Please wait {seconds}s (protects against being blocked).",
        "ru": "⏳ Подожди {seconds} с (защита от блокировки).",
        "uk": "⏳ Зачекай {seconds} с (захист від блокування).",
    },
    "rule.radius_active": {
        "de": "\n📍 Umkreis aktiv: {place}", "en": "\n📍 Radius active: {place}",
        "ru": "\n📍 Радиус активен: {place}", "uk": "\n📍 Радіус активний: {place}",
    },
    "rule.radius_unknown": {
        "de": "\n⚠️ Ort <b>{place}</b> wurde nicht erkannt — es wurde "
        "deutschlandweit gesucht! PLZ prüfen und Suche neu anlegen.",
        "en": "\n⚠️ Location <b>{place}</b> was not recognised — the search ran "
        "across all of Germany! Check the postcode and create the search again.",
        "ru": "\n⚠️ Место <b>{place}</b> не распознано — поиск прошёл по всей "
        "Германии! Проверь индекс и создай поиск заново.",
        "uk": "\n⚠️ Місце <b>{place}</b> не розпізнано — пошук пройшов по всій "
        "Німеччині! Перевір індекс і створи пошук заново.",
    },
    # --- The wizard's "how many hits does this get" preview ----------------
    "rule.preview_testing": {
        "de": "🔎 Kurzer Test, wie viele Treffer das gerade gibt…",
        "en": "🔎 Quick check of how many hits this gets right now…",
        "ru": "🔎 Быстрая проверка, сколько находок это даёт сейчас…",
        "uk": "🔎 Швидка перевірка, скільки знахідок це дає зараз…",
    },
    "rule.preview_none": {
        "de": "🔎 <b>0 Treffer</b> mit diesen Angaben.\n",
        "en": "🔎 <b>0 hits</b> with these settings.\n",
        "ru": "🔎 <b>0 находок</b> с этими настройками.\n",
        "uk": "🔎 <b>0 знахідок</b> з цими налаштуваннями.\n",
    },
    "rule.preview_none_hint": {
        "de": "oder die Suchbegriffe sind zu eng. Ändern geht später jederzeit.",
        "en": "or the keywords are too narrow. You can change it any time later.",
        "ru": "или ключевые слова слишком узкие. Изменить можно в любой момент.",
        "uk": "або ключові слова надто вузькі. Змінити можна будь-коли.",
    },
    "rule.preview_found": {
        "de": "🔎 <b>{count} Treffer</b> gerade online",
        "en": "🔎 <b>{count} hits</b> online right now",
        "ru": "🔎 <b>{count} находок</b> сейчас онлайн",
        "uk": "🔎 <b>{count} знахідок</b> зараз онлайн",
    },
    "rule.preview_cheapest": {
        "de": "\nGünstigstes: {amount}", "en": "\nCheapest: {amount}",
        "ru": "\nСамое дешёвое: {amount}", "uk": "\nНайдешевше: {amount}",
    },
    "rule.tier_interval": {
        "de": "⏱ In deinem Tarif ist das schnellste Intervall {minutes} min — "
        "auf {minutes} min gesetzt.{hint}",
        "en": "⏱ Your plan's fastest interval is {minutes} min — set to "
        "{minutes} min.{hint}",
        "ru": "⏱ В твоём тарифе самый быстрый интервал {minutes} мин — "
        "установлено {minutes} мин.{hint}",
        "uk": "⏱ У твоєму тарифі найшвидший інтервал {minutes} хв — "
        "встановлено {minutes} хв.{hint}",
    },
    "rule.tier_interval_hint": {
        "de": " {label} prüft ab {minutes} min — /premium",
        "en": " {label} checks from {minutes} min — /premium",
        "ru": " {label} проверяет от {minutes} мин — /premium",
        "uk": " {label} перевіряє від {minutes} хв — /premium",
    },
    # --- The three paid filters: what they can and cannot do ---------------
    "edit.ask_condition": {
        "de": "🏷 <b>Zustand</b>\n\n"
        "Kleinanzeigen schreibt den Zustand nicht in die Trefferliste — ich lese "
        "ihn aus Titel und Beschreibung („neu“, „OVP“, „versiegelt“, „defekt“, "
        "„Bastler“). Anzeigen ohne solche Wörter zählen als <b>gebraucht</b>, "
        "einzelne Treffer können dir also durchrutschen oder fehlen.\n"
        "Auf eBay filtert eBay selbst, Idealo liefert bei „gebraucht“ und "
        "„defekt“ nichts — dort gibt es nur Neuware.",
        "en": "🏷 <b>Condition</b>\n\n"
        "Kleinanzeigen does not state the condition in its result list — I read "
        "it from the title and description („neu“, „OVP“, „versiegelt“, "
        "„defekt“, „Bastler“). Ads that say none of this count as <b>used</b>, "
        "so the odd listing may slip through or go missing.\n"
        "On eBay the site filters itself; Idealo returns nothing for used or "
        "faulty — it sells new goods only.",
        "ru": "🏷 <b>Состояние</b>\n\n"
        "Kleinanzeigen не указывает состояние в списке — я читаю его из "
        "заголовка и описания («neu», «OVP», «versiegelt», «defekt», "
        "«Bastler»). Объявления без таких слов считаются <b>б/у</b>, поэтому "
        "отдельные находки могут проскочить или потеряться.\n"
        "На eBay фильтрует сам eBay, Idealo по «б/у» и «неисправно» не даёт "
        "ничего — там только новые товары.",
        "uk": "🏷 <b>Стан</b>\n\n"
        "Kleinanzeigen не зазначає стан у списку — я читаю його із заголовка "
        "та опису («neu», «OVP», «versiegelt», «defekt», «Bastler»). "
        "Оголошення без таких слів вважаються <b>вживаними</b>, тож окремі "
        "знахідки можуть прослизнути або зникнути.\n"
        "На eBay фільтрує сам eBay, Idealo за «вживане» і «несправне» не дає "
        "нічого — там лише нові товари.",
    },
    "edit.ask_shipping": {
        "de": "📦 <b>Versand</b>\n\n"
        "Zieht bei Kleinanzeigen, wo „Versand möglich“ auf der Karte steht. "
        "Plattformen, die nichts dazu sagen (z. B. eBay), werden nicht "
        "gefiltert — sonst wäre deine Regel dort schlagartig leer.",
        "en": "📦 <b>Shipping</b>\n\n"
        "Works on Kleinanzeigen, where the card says whether the seller ships. "
        "Marketplaces that say nothing about it (eBay, for one) are not "
        "filtered — your rule would simply be empty there.",
        "ru": "📦 <b>Доставка</b>\n\n"
        "Работает на Kleinanzeigen, где это указано на карточке. Площадки, "
        "которые об этом молчат (например, eBay), не фильтруются — иначе твоё "
        "правило там мгновенно опустело бы.",
        "uk": "📦 <b>Доставка</b>\n\n"
        "Працює на Kleinanzeigen, де це зазначено на картці. Майданчики, які "
        "про це мовчать (наприклад, eBay), не фільтруються — інакше твоє "
        "правило там миттєво спорожніло б.",
    },
    "edit.ask_auctions": {
        "de": "🔨 <b>Auktionen</b>\n\n"
        "Ein Auktionspreis ist bis zum letzten Gebot nicht echt und verzerrt "
        "den Deal-Score. Blende Auktionen aus, wenn du nur Festpreise willst.",
        "en": "🔨 <b>Auctions</b>\n\n"
        "An auction price is not a real price until the last bid, and it skews "
        "the deal score. Hide auctions if you only want fixed prices.",
        "ru": "🔨 <b>Аукционы</b>\n\n"
        "Цена аукциона до последней ставки ненастоящая и искажает балл сделки. "
        "Скрой аукционы, если хочешь только фиксированные цены.",
        "uk": "🔨 <b>Аукціони</b>\n\n"
        "Ціна аукціону до останньої ставки несправжня і викривлює бал угоди. "
        "Сховай аукціони, якщо хочеш лише фіксовані ціни.",
    },
    "edit.power_pitch": {
        "de": "\n\n🔒 <b>Zustand, Versand &amp; Auktionen</b> gibt es ab "
        "<b>{level}</b>:\n"
        "• nur Neu/OVP — oder gezielt Defekt &amp; Bastler zum Herrichten\n"
        "• nur Anzeigen mit Versand — oder nur Abholung in deiner Nähe\n"
        "• Auktionen ausblenden und nur Festpreise sehen\n"
        "→ /premium",
        "en": "\n\n🔒 <b>Condition, shipping &amp; auctions</b> come with "
        "<b>{level}</b>:\n"
        "• new and sealed only — or faulty and for-parts on purpose\n"
        "• only ads that ship — or only pickup near you\n"
        "• hide auctions and see fixed prices only\n"
        "→ /premium",
        "ru": "\n\n🔒 <b>Состояние, доставка и аукционы</b> доступны с "
        "<b>{level}</b>:\n"
        "• только новое/запечатанное — или наоборот, неисправное под ремонт\n"
        "• только объявления с доставкой — или только самовывоз рядом\n"
        "• скрыть аукционы и видеть только фиксированные цены\n"
        "→ /premium",
        "uk": "\n\n🔒 <b>Стан, доставка та аукціони</b> доступні з "
        "<b>{level}</b>:\n"
        "• лише нове/запечатане — або навпаки, несправне під ремонт\n"
        "• лише оголошення з доставкою — або лише самовивіз поруч\n"
        "• сховати аукціони й бачити тільки фіксовані ціни\n"
        "→ /premium",
    },
    "edit.power_alert": {
        "de": "🔒 Zustand-, Versand- und Auktions-Filter gibt es ab {level}. "
        "Mehr dazu: /premium",
        "en": "🔒 Condition, shipping and auction filters come with {level}. "
        "More: /premium",
        "ru": "🔒 Фильтры состояния, доставки и аукционов доступны с {level}. "
        "Подробнее: /premium",
        "uk": "🔒 Фільтри стану, доставки та аукціонів доступні з {level}. "
        "Докладніше: /premium",
    },
    "edit.price_invalid": {
        "de": "⚠️ Bitte Zahl oder Bereich senden (z. B. 1200 oder 500-1200).",
        "en": "⚠️ Please send a number or a range (e.g. 1200 or 500-1200).",
        "ru": "⚠️ Пришли число или диапазон (напр. 1200 или 500-1200).",
        "uk": "⚠️ Надішли число або діапазон (напр. 1200 або 500-1200).",
    },
    "edit.not_found": {
        "de": "Nicht gefunden", "en": "Not found",
        "ru": "Не найдено", "uk": "Не знайдено",
    },
    "edit.ask_vehicle": {
        "de": "🚗 Kilometer und Baujahr.\n"
        "z. B. <code>100000 2018</code> (max. km + ab Baujahr), "
        "<code>100000</code> (nur km), <code>2018</code> (nur Baujahr), "
        "<code>{clear}</code> = beides löschen.\n\n"
        "<i>Angebote ohne Angabe bleiben drin — sonst würde eine Layout-"
        "Änderung die Suche stillschweigend leeren.</i>",
        "en": "🚗 Mileage and year of registration.\n"
        "e.g. <code>100000 2018</code> (max km + from year), "
        "<code>100000</code> (km only), <code>2018</code> (year only), "
        "<code>{clear}</code> = clear both.\n\n"
        "<i>Listings that state neither are kept — otherwise a layout change "
        "would silently empty the search.</i>",
        "ru": "🚗 Пробег и год выпуска.\n"
        "напр. <code>100000 2018</code> (макс. км + от года), "
        "<code>100000</code> (только км), <code>2018</code> (только год), "
        "<code>{clear}</code> = очистить оба.\n\n"
        "<i>Объявления без указания остаются — иначе смена вёрстки молча "
        "опустошила бы поиск.</i>",
        "uk": "🚗 Пробіг і рік випуску.\n"
        "напр. <code>100000 2018</code> (макс. км + від року), "
        "<code>100000</code> (лише км), <code>2018</code> (лише рік), "
        "<code>{clear}</code> = очистити обидва.\n\n"
        "<i>Оголошення без зазначення залишаються — інакше зміна вёрстки "
        "мовчки спорожнила б пошук.</i>",
    },
    "edit.vehicle_invalid": {
        "de": "⚠️ Bitte Kilometer und/oder Baujahr senden, z. B. "
        "<code>100000 2018</code>.",
        "en": "⚠️ Please send mileage and/or year, e.g. <code>100000 2018</code>.",
        "ru": "⚠️ Пришли пробег и/или год, напр. <code>100000 2018</code>.",
        "uk": "⚠️ Надішли пробіг і/або рік, напр. <code>100000 2018</code>.",
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
    # --- The short path: one sentence instead of eight questions -------------
    "rule.ask_sentence": {
        "de": "✍️ Beschreib in einem Satz, was du suchst.\n\n"
        "<i>Tesla Model 3 unter 25.000 €, 100 km um Worms, keine Unfallwagen</i>",
        "en": "✍️ Describe what you are looking for in one sentence.\n\n"
        "<i>Tesla Model 3 under €25,000, within 100 km of Worms, no salvage</i>",
        "ru": "✍️ Опиши одним предложением, что ты ищешь.\n\n"
        "<i>Tesla Model 3 до 25 000 €, 100 км вокруг Вормса, без аварийных</i>",
        "uk": "✍️ Опиши одним реченням, що ти шукаєш.\n\n"
        "<i>Tesla Model 3 до 25 000 €, 100 км навколо Вормса, без аварійних</i>",
    },
    "rule.sentence_unclear": {
        "de": "🤔 Daraus konnte ich keine Suchbegriffe lesen. Schreib den Satz "
        "anders — oder leg die Suche Schritt für Schritt an.",
        "en": "🤔 I could not read any keywords from that. Try another wording — "
        "or set the search up step by step.",
        "ru": "🤔 Я не смог выделить ключевые слова. Сформулируй иначе — "
        "или создай поиск пошагово.",
        "uk": "🤔 Я не зміг виділити ключові слова. Сформулюй інакше — "
        "або створи пошук покроково.",
    },
    "rule.sentence_understood": {
        "de": "So habe ich das verstanden:",
        "en": "Here is what I understood:",
        "ru": "Вот как я это понял:",
        "uk": "Ось як я це зрозумів:",
    },
    "rule.f_keywords": {"de": "Suche", "en": "Search", "ru": "Поиск", "uk": "Пошук"},
    "rule.f_price": {"de": "Preis", "en": "Price", "ru": "Цена", "uk": "Ціна"},
    "rule.f_place": {"de": "Ort", "en": "Location", "ru": "Место", "uk": "Місце"},
    "rule.f_condition": {
        "de": "Zustand", "en": "Condition", "ru": "Состояние", "uk": "Стан",
    },
    "rule.f_exclude": {
        "de": "Ohne", "en": "Without", "ru": "Без", "uk": "Без",
    },
    "rule.f_mileage": {
        "de": "Kilometer", "en": "Mileage", "ru": "Пробег", "uk": "Пробіг",
    },
    "rule.f_any": {"de": "beliebig", "en": "any", "ru": "любая", "uk": "будь-яка"},
    "rule.f_everywhere": {
        "de": "überall", "en": "everywhere", "ru": "везде", "uk": "всюди",
    },
    "btn.rule_steps": {
        "de": "📋 Schritt für Schritt",
        "en": "📋 Step by step",
        "ru": "📋 Пошагово",
        "uk": "📋 Покроково",
    },
    "btn.draft_save": {
        "de": "✅ So suchen",
        "en": "✅ Search like this",
        "ru": "✅ Искать так",
        "uk": "✅ Шукати так",
    },
    "btn.draft_adjust": {
        "de": "⚙️ Anpassen",
        "en": "⚙️ Adjust",
        "ru": "⚙️ Настроить",
        "uk": "⚙️ Налаштувати",
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
    "premium.compare_sites": {
        "de": "• Marktplätze pro Suche: {sites}",
        "en": "• Marketplaces per search: {sites}",
        "ru": "• Площадок на поиск: {sites}",
        "uk": "• Майданчиків на пошук: {sites}",
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
    "usage.kind.photo_day": {"de": "Foto-Bewertungen (Fair Use)",
                             "en": "Photo valuations (fair use)",
                             "ru": "Оценки по фото (честное использование)",
                             "uk": "Оцінки за фото (чесне використання)"},
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
    "privacy.page": {
        "de": "🔐 <b>Deine Daten</b>\n\n"
        "<b>Was gespeichert wird</b>\n"
        "• Telegram-ID, Name/Username, Sprache\n"
        "• Deine Suchen (Begriffe, Ort, Preisrahmen, Intervall)\n"
        "• Gefundene Anzeigen deiner Suchen samt Favoriten und Preisverlauf\n"
        "• Deine Flips (Kauf-/Verkaufspreis, Gewinn)\n"
        "• Zahlungen: Betrag, Datum, Zahlungs-ID von Telegram\n\n"
        "<b>Was NICHT gespeichert wird</b>\n"
        "• Keine Telefonnummer, keine Adresse, keine Zahlungsdaten — "
        "die Abwicklung läuft komplett bei Telegram\n\n"
        "<b>Fotos</b>\n"
        "Bilder für die Foto-Bewertung werden zur Erkennung an einen "
        "KI-Dienst übertragen und danach nicht dauerhaft gespeichert.\n\n"
        "<b>Deine Rechte</b>\n"
        "• /meinedaten — Export als JSON-Datei\n"
        "• /loeschen — alles endgültig löschen\n\n"
        "Fragen? /support",
        "en": "🔐 <b>Your data</b>\n\n"
        "<b>What is stored</b>\n"
        "• Telegram ID, name/username, language\n"
        "• Your search rules (terms, place, price range, interval)\n"
        "• Listings your rules found, including favorites and price history\n"
        "• Your flips (buy/sell price, profit)\n"
        "• Payments: amount, date, payment ID from Telegram\n\n"
        "<b>What is NOT stored</b>\n"
        "• No phone number, no address, no payment details — "
        "Telegram handles the whole transaction\n\n"
        "<b>Photos</b>\n"
        "Images for the photo valuation are passed to an AI service for "
        "recognition and are not kept permanently afterwards.\n\n"
        "<b>Your rights</b>\n"
        "• /meinedaten — export as a JSON file\n"
        "• /loeschen — erase everything for good\n\n"
        "Questions? /support",
        "ru": "🔐 <b>Твои данные</b>\n\n"
        "<b>Что сохраняется</b>\n"
        "• Telegram-ID, имя/username, язык\n"
        "• Твои правила поиска (запросы, место, диапазон цен, интервал)\n"
        "• Найденные объявления вместе с избранным и историей цен\n"
        "• Твои флипы (цена покупки/продажи, прибыль)\n"
        "• Платежи: сумма, дата, ID платежа от Telegram\n\n"
        "<b>Что НЕ сохраняется</b>\n"
        "• Ни номера телефона, ни адреса, ни платёжных данных — "
        "вся оплата проходит на стороне Telegram\n\n"
        "<b>Фото</b>\n"
        "Снимки для оценки по фото передаются на распознавание в ИИ-сервис "
        "и после этого постоянно не хранятся.\n\n"
        "<b>Твои права</b>\n"
        "• /meinedaten — выгрузка в виде JSON-файла\n"
        "• /loeschen — удалить всё окончательно\n\n"
        "Вопросы? /support",
        "uk": "🔐 <b>Твої дані</b>\n\n"
        "<b>Що зберігається</b>\n"
        "• Telegram-ID, ім'я/username, мова\n"
        "• Твої правила пошуку (запити, місце, діапазон цін, інтервал)\n"
        "• Знайдені оголошення разом з обраним та історією цін\n"
        "• Твої фліпи (ціна купівлі/продажу, прибуток)\n"
        "• Платежі: сума, дата, ID платежу від Telegram\n\n"
        "<b>Що НЕ зберігається</b>\n"
        "• Ні номера телефону, ні адреси, ні платіжних даних — "
        "уся оплата проходить на боці Telegram\n\n"
        "<b>Фото</b>\n"
        "Знімки для оцінки за фото передаються на розпізнавання в ШІ-сервіс "
        "і після цього постійно не зберігаються.\n\n"
        "<b>Твої права</b>\n"
        "• /meinedaten — вивантаження у вигляді JSON-файлу\n"
        "• /loeschen — видалити все остаточно\n\n"
        "Питання? /support",
    },
    "privacy.export_caption": {
        "de": "📦 Das ist alles, was über dich gespeichert ist.",
        "en": "📦 That is everything stored about you.",
        "ru": "📦 Это всё, что о тебе сохранено.",
        "uk": "📦 Це все, що про тебе збережено.",
    },
    #: Attachment name of the data export — ASCII only, it travels as a filename.
    "privacy.export_filename": {
        "de": "meine-daten-{id}.json",
        "en": "my-data-{id}.json",
        "ru": "moi-dannye-{id}.json",
        "uk": "moi-dani-{id}.json",
    },
    "privacy.delete_confirm": {
        "de": "🗑 <b>Alle Daten löschen?</b>\n\n"
        "Das entfernt endgültig: dein Profil, alle Suchen, alle gefundenen "
        "Anzeigen, Favoriten und Flips.\n\n"
        "⚠️ Ein laufendes Premium-Abo musst du <b>vorher</b> in Telegram "
        "kündigen — sonst läuft die Abbuchung weiter.\n"
        "ℹ️ Zahlungsbelege bleiben anonymisiert erhalten (gesetzliche "
        "Aufbewahrungspflicht), sie lassen sich dir dann nicht mehr zuordnen.",
        "en": "🗑 <b>Delete all data?</b>\n\n"
        "This permanently removes: your profile, every search rule, every "
        "listing found for you, favorites and flips.\n\n"
        "⚠️ A running Premium plan has to be cancelled in Telegram "
        "<b>first</b> — otherwise the charges keep running.\n"
        "ℹ️ Payment records stay in anonymised form (legal retention duty); "
        "they can no longer be linked to you.",
        "ru": "🗑 <b>Удалить все данные?</b>\n\n"
        "Окончательно удаляются: твой профиль, все правила поиска, все "
        "найденные объявления, избранное и флипы.\n\n"
        "⚠️ Действующую подписку Premium нужно <b>сначала</b> отменить в "
        "Telegram — иначе списания продолжатся.\n"
        "ℹ️ Платёжные записи остаются обезличенными (требование закона о "
        "хранении), связать их с тобой уже нельзя.",
        "uk": "🗑 <b>Видалити всі дані?</b>\n\n"
        "Остаточно видаляються: твій профіль, усі правила пошуку, усі "
        "знайдені оголошення, обране та фліпи.\n\n"
        "⚠️ Чинну підписку Premium треба <b>спершу</b> скасувати в "
        "Telegram — інакше списання триватимуть.\n"
        "ℹ️ Платіжні записи лишаються знеособленими (вимога закону про "
        "зберігання), пов'язати їх із тобою вже не можна.",
    },
    "privacy.btn_delete_all": {
        "de": "🗑 Ja, alles löschen", "en": "🗑 Yes, erase everything",
        "ru": "🗑 Да, удалить всё", "uk": "🗑 Так, видалити все",
    },
    "privacy.delete_aborted": {
        "de": "✅ Nichts gelöscht — alles bleibt wie es ist.",
        "en": "✅ Nothing erased — everything stays as it is.",
        "ru": "✅ Ничего не удалено — всё осталось как было.",
        "uk": "✅ Нічого не видалено — усе лишилося як було.",
    },
    "privacy.deleted": {
        "de": "🗑 Erledigt, {name}. Alle deine Daten sind gelöscht.\n\n"
        "Mit /start kannst du jederzeit neu anfangen — dann wie ein "
        "komplett neuer Nutzer.",
        "en": "🗑 Done, {name}. All of your data is gone.\n\n"
        "You can start over any time with /start — as a completely new user.",
        "ru": "🗑 Готово, {name}. Все твои данные удалены.\n\n"
        "Начать заново можно в любой момент через /start — уже как "
        "совершенно новый пользователь.",
        "uk": "🗑 Готово, {name}. Усі твої дані видалено.\n\n"
        "Почати заново можна будь-коли через /start — уже як цілком "
        "новий користувач.",
    },
    "privacy.deleted_toast": {
        "de": "Gelöscht", "en": "Erased",
        "ru": "Удалено", "uk": "Видалено",
    },

    # --- Support chat ------------------------------------------------------
    "support.prompt": {
        "de": "💬 <b>Support</b>\n\n"
        "Schreib mir jetzt deine Frage oder dein Problem in EINER Nachricht — "
        "ich leite sie direkt an das Team weiter.\n"
        "(/cancel zum Abbrechen)",
        "en": "💬 <b>Support</b>\n\n"
        "Write your question or problem in ONE message now — I pass it "
        "straight on to the team.\n"
        "(/cancel to abort)",
        "ru": "💬 <b>Поддержка</b>\n\n"
        "Напиши свой вопрос или проблему ОДНИМ сообщением — я передам его "
        "прямо команде.\n"
        "(/cancel — отмена)",
        "uk": "💬 <b>Підтримка</b>\n\n"
        "Напиши своє питання або проблему ОДНИМ повідомленням — я передам "
        "його прямо команді.\n"
        "(/cancel — скасувати)",
    },
    "support.empty": {
        "de": "⚠️ Leere Nachricht — bitte nochmal /support.",
        "en": "⚠️ Empty message — please use /support again.",
        "ru": "⚠️ Пустое сообщение — попробуй /support ещё раз.",
        "uk": "⚠️ Порожнє повідомлення — спробуй /support ще раз.",
    },
    "support.delivered": {
        "de": "✅ Deine Nachricht ist beim Team! Du bekommst die Antwort "
        "direkt hier im Chat.",
        "en": "✅ Your message reached the team! The answer lands right here "
        "in the chat.",
        "ru": "✅ Твоё сообщение у команды! Ответ придёт прямо сюда, в чат.",
        "uk": "✅ Твоє повідомлення в команди! Відповідь прийде прямо сюди, "
        "у чат.",
    },
    "support.undelivered": {
        "de": "⚠️ Gerade ist leider kein Team-Mitglied erreichbar — deine "
        "Nachricht konnte nicht zugestellt werden. Bitte versuch es "
        "später nochmal.",
        "en": "⚠️ No one from the team is reachable right now — your message "
        "could not be delivered. Please try again later.",
        "ru": "⚠️ Сейчас никто из команды недоступен — сообщение не "
        "доставлено. Попробуй, пожалуйста, позже.",
        "uk": "⚠️ Зараз ніхто з команди недоступний — повідомлення не "
        "доставлено. Спробуй, будь ласка, пізніше.",
    },
    "support.answer": {
        "de": "💬 <b>Antwort vom Support:</b>\n\n{text}\n\n"
        "Weitere Fragen? Einfach nochmal /support.",
        "en": "💬 <b>Reply from support:</b>\n\n{text}\n\n"
        "More questions? Just use /support again.",
        "ru": "💬 <b>Ответ поддержки:</b>\n\n{text}\n\n"
        "Ещё вопросы? Просто снова /support.",
        "uk": "💬 <b>Відповідь підтримки:</b>\n\n{text}\n\n"
        "Ще питання? Просто знову /support.",
    },

    # --- Flip tracker (/flips, /profit) -------------------------------------
    "flip.not_found": {
        "de": "Nicht gefunden", "en": "Not found",
        "ru": "Не найдено", "uk": "Не знайдено",
    },
    "flip.listing_gone": {
        "de": "⚠️ Angebot nicht mehr gefunden.",
        "en": "⚠️ That listing is gone.",
        "ru": "⚠️ Объявление больше не найдено.",
        "uk": "⚠️ Оголошення більше не знайдено.",
    },
    "flip.gone": {
        "de": "⚠️ Flip nicht mehr gefunden.",
        "en": "⚠️ That flip is gone.",
        "ru": "⚠️ Флип больше не найден.",
        "uk": "⚠️ Фліп більше не знайдено.",
    },
    "flip.need_amount": {
        "de": "⚠️ Bitte einen Betrag senden, z. B. <code>{example}</code>.",
        "en": "⚠️ Please send an amount, e.g. <code>{example}</code>.",
        "ru": "⚠️ Пришли сумму, например <code>{example}</code>.",
        "uk": "⚠️ Надішли суму, наприклад <code>{example}</code>.",
    },
    "flip.ask_buy_price": {
        "de": "🛒 <b>{title}</b>\n\n"
        "Für wie viel hast du gekauft? Angebotspreis: <b>{price}</b>\n"
        "Zahl senden — oder <code>ok</code>, wenn du zum Angebotspreis "
        "gekauft hast.\n"
        "(/cancel zum Abbrechen)",
        "en": "🛒 <b>{title}</b>\n\n"
        "What did you pay? Listed price: <b>{price}</b>\n"
        "Send a number — or <code>ok</code> if you paid the listed price.\n"
        "(/cancel to abort)",
        "ru": "🛒 <b>{title}</b>\n\n"
        "За сколько ты купил? Цена объявления: <b>{price}</b>\n"
        "Пришли число — или <code>ok</code>, если купил по цене "
        "объявления.\n"
        "(/cancel — отмена)",
        "uk": "🛒 <b>{title}</b>\n\n"
        "За скільки ти купив? Ціна оголошення: <b>{price}</b>\n"
        "Надішли число — або <code>ok</code>, якщо купив за ціною "
        "оголошення.\n"
        "(/cancel — скасувати)",
    },
    "flip.expected_net": {
        "de": "\n📈 Erwarteter Netto-Gewinn beim Verkauf zum Marktpreis "
        "({market}): <b>{net}</b>",
        "en": "\n📈 Expected net profit when sold at market price "
        "({market}): <b>{net}</b>",
        "ru": "\n📈 Ожидаемая чистая прибыль при продаже по рыночной цене "
        "({market}): <b>{net}</b>",
        "uk": "\n📈 Очікуваний чистий прибуток під час продажу за ринковою "
        "ціною ({market}): <b>{net}</b>",
    },
    "flip.bought": {
        "de": "✅ Gekauft für <b>{price}</b> — im Lager.{extra}\n\n"
        "📦 Offen: {open} Flip(s), investiert {invested}\n"
        "Verkauft? → /flips → {sold}",
        "en": "✅ Bought for <b>{price}</b> — in your inventory.{extra}\n\n"
        "📦 Open: {open} flip(s), {invested} invested\n"
        "Sold it? → /flips → {sold}",
        "ru": "✅ Куплено за <b>{price}</b> — на складе.{extra}\n\n"
        "📦 Открыто: {open} флип(ов), вложено {invested}\n"
        "Продал? → /flips → {sold}",
        "uk": "✅ Куплено за <b>{price}</b> — на складі.{extra}\n\n"
        "📦 Відкрито: {open} фліп(ів), вкладено {invested}\n"
        "Продав? → /flips → {sold}",
    },
    "flip.title": {
        "de": "📦 <b>Meine Flips</b>", "en": "📦 <b>My flips</b>",
        "ru": "📦 <b>Мои флипы</b>", "uk": "📦 <b>Мої фліпи</b>",
    },
    "flip.mode_line": {
        "de": "🎯 Flip-Modus: <b>{mode}</b>", "en": "🎯 Flip mode: <b>{mode}</b>",
        "ru": "🎯 Режим флипа: <b>{mode}</b>", "uk": "🎯 Режим фліпа: <b>{mode}</b>",
    },
    "flip.mode_off": {"de": "aus", "en": "off", "ru": "выкл", "uk": "вимк"},
    "flip.mode_min": {
        "de": "≥ {amount} netto", "en": "≥ {amount} net",
        "ru": "≥ {amount} чистыми", "uk": "≥ {amount} чистими",
    },
    "flip.realised": {
        "de": "💰 Realisierter Gewinn: <b>{net}</b> ({count} verkauft) · "
        "30 Tage: {net30}",
        "en": "💰 Realised profit: <b>{net}</b> ({count} sold) · "
        "30 days: {net30}",
        "ru": "💰 Реализованная прибыль: <b>{net}</b> (продано {count}) · "
        "30 дней: {net30}",
        "uk": "💰 Реалізований прибуток: <b>{net}</b> (продано {count}) · "
        "30 днів: {net30}",
    },
    "flip.in_stock": {
        "de": "📦 Im Lager: <b>{count}</b> · investiert {invested}",
        "en": "📦 In stock: <b>{count}</b> · {invested} invested",
        "ru": "📦 На складе: <b>{count}</b> · вложено {invested}",
        "uk": "📦 На складі: <b>{count}</b> · вкладено {invested}",
    },
    "flip.stock_header": {
        "de": "<b>Im Lager:</b>", "en": "<b>In stock:</b>",
        "ru": "<b>На складе:</b>", "uk": "<b>На складі:</b>",
    },
    "flip.stock_row": {
        "de": "• <b>{title}</b> — gekauft {price} ({date})",
        "en": "• <b>{title}</b> — bought {price} ({date})",
        "ru": "• <b>{title}</b> — куплено {price} ({date})",
        "uk": "• <b>{title}</b> — куплено {price} ({date})",
    },
    "flip.stock_empty": {
        "de": "Noch nichts im Lager. Auf einer Deal-Karte 🛒 drücken.",
        "en": "Nothing in stock yet. Tap 🛒 on a deal card.",
        "ru": "На складе пока пусто. Нажми 🛒 на карточке сделки.",
        "uk": "На складі поки порожньо. Натисни 🛒 на картці угоди.",
    },
    "flip.btn_sold": {
        "de": "✅ Verkauft: {title}", "en": "✅ Sold: {title}",
        "ru": "✅ Продано: {title}", "uk": "✅ Продано: {title}",
    },
    "flip.sold_word": {
        "de": "✅ Verkauft", "en": "✅ Sold",
        "ru": "✅ Продано", "uk": "✅ Продано",
    },
    "flip.btn_profit": {
        "de": "📈 Gewinn-Statistik", "en": "📈 Profit stats",
        "ru": "📈 Статистика прибыли", "uk": "📈 Статистика прибутку",
    },
    "flip.btn_mode": {
        "de": "🎯 Flip-Modus", "en": "🎯 Flip mode",
        "ru": "🎯 Режим флипа", "uk": "🎯 Режим фліпа",
    },
    "flip.btn_back_to_flips": {
        "de": "⬅️ Zu den Flips", "en": "⬅️ Back to the flips",
        "ru": "⬅️ К флипам", "uk": "⬅️ До фліпів",
    },
    "flip.removed": {
        "de": "✖️ Entfernt", "en": "✖️ Removed",
        "ru": "✖️ Удалено", "uk": "✖️ Видалено",
    },
    "flip.ask_sell_price": {
        "de": "💸 <b>{title}</b>\n"
        "Gekauft für {price}. Für wie viel verkauft?\n"
        "(/cancel zum Abbrechen)",
        "en": "💸 <b>{title}</b>\n"
        "Bought for {price}. What did you sell it for?\n"
        "(/cancel to abort)",
        "ru": "💸 <b>{title}</b>\n"
        "Куплено за {price}. За сколько продал?\n"
        "(/cancel — отмена)",
        "uk": "💸 <b>{title}</b>\n"
        "Куплено за {price}. За скільки продав?\n"
        "(/cancel — скасувати)",
    },
    "flip.sold_result": {
        "de": "{icon} <b>Verkauft für {price}</b>\n\n"
        "Einkauf {buy} · Gebühren+Versand {fees}\n"
        "💰 Netto-Gewinn: <b>{net}</b> (ROI {roi})\n\n"
        "📈 Gesamt realisiert: <b>{total}</b> aus {count} Flip(s)",
        "en": "{icon} <b>Sold for {price}</b>\n\n"
        "Purchase {buy} · fees+shipping {fees}\n"
        "💰 Net profit: <b>{net}</b> (ROI {roi})\n\n"
        "📈 Realised in total: <b>{total}</b> from {count} flip(s)",
        "ru": "{icon} <b>Продано за {price}</b>\n\n"
        "Покупка {buy} · комиссии+доставка {fees}\n"
        "💰 Чистая прибыль: <b>{net}</b> (ROI {roi})\n\n"
        "📈 Всего реализовано: <b>{total}</b> из {count} флип(ов)",
        "uk": "{icon} <b>Продано за {price}</b>\n\n"
        "Купівля {buy} · комісії+доставка {fees}\n"
        "💰 Чистий прибуток: <b>{net}</b> (ROI {roi})\n\n"
        "📈 Усього реалізовано: <b>{total}</b> з {count} фліп(ів)",
    },
    "flip.profit_title": {
        "de": "📈 <b>Gewinn-Statistik</b>", "en": "📈 <b>Profit stats</b>",
        "ru": "📈 <b>Статистика прибыли</b>", "uk": "📈 <b>Статистика прибутку</b>",
    },
    "flip.profit_empty": {
        "de": "Noch keine Flips. Auf einer Deal-Karte 🛒 drücken, wenn du "
        "kaufst — ab dann rechnet der Bot deinen echten Gewinn mit.",
        "en": "No flips yet. Tap 🛒 on a deal card when you buy — from then "
        "on the bot tracks your real profit.",
        "ru": "Флипов пока нет. Нажми 🛒 на карточке сделки при покупке — "
        "дальше бот считает твою реальную прибыль.",
        "uk": "Фліпів поки немає. Натисни 🛒 на картці угоди під час "
        "покупки — далі бот рахує твій реальний прибуток.",
    },
    "flip.profit_total": {
        "de": "💰 Netto-Gewinn gesamt: <b>{net}</b>",
        "en": "💰 Net profit in total: <b>{net}</b>",
        "ru": "💰 Чистая прибыль всего: <b>{net}</b>",
        "uk": "💰 Чистий прибуток усього: <b>{net}</b>",
    },
    "flip.profit_30d": {
        "de": "📅 Letzte 30 Tage: <b>{net}</b>",
        "en": "📅 Last 30 days: <b>{net}</b>",
        "ru": "📅 Последние 30 дней: <b>{net}</b>",
        "uk": "📅 Останні 30 днів: <b>{net}</b>",
    },
    "flip.profit_sold": {
        "de": "🛒 Verkauft: {count} · Umsatz {revenue} · Gebühren {fees}",
        "en": "🛒 Sold: {count} · revenue {revenue} · fees {fees}",
        "ru": "🛒 Продано: {count} · оборот {revenue} · комиссии {fees}",
        "uk": "🛒 Продано: {count} · оборот {revenue} · комісії {fees}",
    },
    "flip.profit_margin": {
        "de": "📊 Ø Marge auf Einkauf: <b>{percent}%</b>",
        "en": "📊 Avg. margin on purchase: <b>{percent}%</b>",
        "ru": "📊 Средняя маржа к закупке: <b>{percent}%</b>",
        "uk": "📊 Середня маржа до закупівлі: <b>{percent}%</b>",
    },
    "flip.profit_best": {
        "de": "🏆 Bester Flip: {title} (+{net})",
        "en": "🏆 Best flip: {title} (+{net})",
        "ru": "🏆 Лучший флип: {title} (+{net})",
        "uk": "🏆 Найкращий фліп: {title} (+{net})",
    },
    "flip.profit_stock": {
        "de": "📦 Im Lager: {count} · gebunden {invested}",
        "en": "📦 In stock: {count} · {invested} tied up",
        "ru": "📦 На складе: {count} · заморожено {invested}",
        "uk": "📦 На складі: {count} · заморожено {invested}",
    },
    "flip.mode_title": {
        "de": "🎯 <b>Flip-Modus</b>", "en": "🎯 <b>Flip mode</b>",
        "ru": "🎯 <b>Режим флипа</b>", "uk": "🎯 <b>Режим фліпа</b>",
    },
    "flip.mode_body": {
        "de": "Nur Angebote liefern, deren <b>erwarteter Netto-Gewinn</b> "
        "(Marktpreis − Gebühren − Versand − Kaufpreis) mindestens so hoch "
        "ist:\n\nAlles andere wird still verworfen. Preisstürze zählen mit.",
        "en": "Only deliver listings whose <b>expected net profit</b> "
        "(market price − fees − shipping − purchase price) is at least "
        "this high:\n\nEverything else is dropped silently. Price drops "
        "count as well.",
        "ru": "Присылать только объявления, у которых <b>ожидаемая чистая "
        "прибыль</b> (рыночная цена − комиссии − доставка − цена покупки) "
        "не ниже:\n\nВсё остальное тихо отбрасывается. Падения цен тоже "
        "учитываются.",
        "uk": "Надсилати лише оголошення, у яких <b>очікуваний чистий "
        "прибуток</b> (ринкова ціна − комісії − доставка − ціна купівлі) "
        "не нижчий:\n\nУсе інше тихо відкидається. Падіння цін теж "
        "враховуються.",
    },
    "flip.mode_btn_off": {
        "de": "Aus (alles zeigen)", "en": "Off (show everything)",
        "ru": "Выкл (показывать всё)", "uk": "Вимк (показувати все)",
    },
    "flip.mode_set": {
        "de": "🎯 Flip-Modus: {mode}", "en": "🎯 Flip mode: {mode}",
        "ru": "🎯 Режим флипа: {mode}", "uk": "🎯 Режим фліпа: {mode}",
    },

    # --- Quota wording (shared by /premium, /usage and every cap message) ----
    "quota.unlimited": {"de": "unbegrenzt", "en": "unlimited",
                        "ru": "\u0431\u0435\u0437 \u043e\u0433\u0440\u0430\u043d\u0438\u0447\u0435\u043d\u0438\u0439",
                        "uk": "\u0431\u0435\u0437 \u043e\u0431\u043c\u0435\u0436\u0435\u043d\u044c"},
    "quota.window_day": {"de": "heute", "en": "today",
                         "ru": "\u0441\u0435\u0433\u043e\u0434\u043d\u044f", "uk": "\u0441\u044c\u043e\u0433\u043e\u0434\u043d\u0456"},
    "quota.window_month": {"de": "diesen Monat", "en": "this month",
                           "ru": "\u0432 \u044d\u0442\u043e\u043c \u043c\u0435\u0441\u044f\u0446\u0435",
                           "uk": "\u0446\u044c\u043e\u0433\u043e \u043c\u0456\u0441\u044f\u0446\u044f"},
    "quota.unit.cards": {"de": "Karten/Tag", "en": "cards/day",
                         "ru": "\u043a\u0430\u0440\u0442\u043e\u0447\u0435\u043a/\u0434\u0435\u043d\u044c",
                         "uk": "\u043a\u0430\u0440\u0442\u043e\u043a/\u0434\u0435\u043d\u044c"},
    "quota.unit.photo": {"de": "Foto-Bewertungen/Monat", "en": "photo valuations/month",
                         "ru": "\u043e\u0446\u0435\u043d\u043e\u043a \u043f\u043e \u0444\u043e\u0442\u043e/\u043c\u0435\u0441",
                         "uk": "\u043e\u0446\u0456\u043d\u043e\u043a \u0437\u0430 \u0444\u043e\u0442\u043e/\u043c\u0456\u0441"},
    "quota.unit.quick": {"de": "Schnell-Suchen/Tag", "en": "quick searches/day",
                         "ru": "\u0431\u044b\u0441\u0442\u0440\u044b\u0445 \u043f\u043e\u0438\u0441\u043a\u043e\u0432/\u0434\u0435\u043d\u044c",
                         "uk": "\u0448\u0432\u0438\u0434\u043a\u0438\u0445 \u043f\u043e\u0448\u0443\u043a\u0456\u0432/\u0434\u0435\u043d\u044c"},
    "quota.unit.nego": {"de": "Verhandlungen/Monat", "en": "negotiations/month",
                        "ru": "\u043f\u0435\u0440\u0435\u0433\u043e\u0432\u043e\u0440\u043e\u0432/\u043c\u0435\u0441",
                        "uk": "\u043f\u0435\u0440\u0435\u043c\u043e\u0432\u0438\u043d/\u043c\u0456\u0441"},
    "quota.upgrade_hint": {"de": "<b>{level}</b>: {value} \u2014 /premium",
                           "en": "<b>{level}</b>: {value} \u2014 /premium",
                           "ru": "<b>{level}</b>: {value} \u2014 /premium",
                           "uk": "<b>{level}</b>: {value} \u2014 /premium"},
    "quota.unit.days": {"de": "Tage", "en": "days",
                        "ru": "\u0434\u043d\u0435\u0439", "uk": "\u0434\u043d\u0456\u0432"},
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
