# M4.2 – Luna-managed Markdown Context

Реалізуй M4.2 у `softsock/liac-ai` від актуального `main`.

**Мета – спростити керування контекстом: Luna асинхронно редагує один Markdown-документ `context.md`, який безпосередньо впливає на поведінку Nemotron.**

Не створюй Performance Beat Scheduler, новий Attention Engine чи окремих агентів. Ми свідомо повертаємося до простішої початкової концепції.

## 1. Спочатку досліди реалізацію

Прочитай `AGENTS.md`, `PROJECT_BLUEPRINT.md`, документацію M1.5/M2 і відповідні модулі:

- `ContextCompiler`, `ContextEpoch`, `ContextPolicy`.
- `CharacterState`, `NoteProposal`, `DeepRequest/DeepResult`.
- Luna OMP adapter, Deep worker, Journal.

Врахуй, що M4.1 Attention Engine був відкочений із `main`. Не відновлюй його.

Знайди найменшу зміну наявної архітектури, яка дозволить Luna керувати Markdown-контекстом.

## 2. Єдиний робочий context.md

Заміни обмежену `context_note` (1000 символів) на повноцінний текстовий робочий контекст.

Орієнтовний вміст:

```markdown
# Working Context

## Current Situation
The user is redesigning Skin Creator and has changed
the interface several times.

## Open Threads
- The user has not decided whether to keep the new layout.

## Suggested Threads
- If another redesign comes up, tease the user about
  releasing Skin Creator 2 before version 1.
- Be curious whether they genuinely like the new layout
  or are simply tired of changing it.

## Relevant Details
- The user prefers vintage-inspired interface aesthetics.
```

Це приклад, а не жорстка схема.

Luna має свободу змінювати структуру, додавати чи прибирати розділи, конкретні ідеї для реплік, актуальні обставини та незавершені теми.

Suggested Threads можуть містити **майже готові репліки**, а не лише загальні рекомендації. Nemotron сам вирішує, чи використовувати їх і як сформулювати відповідь.

Не змушуй Luna генерувати Suggested Threads у кожному запиті. Порожній або незмінений контекст – нормальний результат.

## 3. Асинхронне редагування

Використай наявний Deep pipeline.

Luna отримує канонічні події, попередній робочий контекст і власну ширшу OMP-історію.

Вона пропонує оновлений Markdown-документ або no-op.

Runtime атомарно застосовує результат до версійованого стану. Збережи перевірку актуальності, захист від конфліктів, відновлення після перезапуску та durable Journal.

Не потрібен складний patch language або JSON для кожного розділу. Якщо OMP RPC потребує структурованої оболонки відповіді, залиш мінімальний транспортний контракт, усередині якого Markdown передається одним текстовим полем.

`context.md` має бути людсько-читаним представленням актуального стану. Не роби файлову систему другим незалежним джерелом правди: стан повинен залишатися узгодженим із SQLite.

## 4. Інтеграція з Fast і KV cache

Збережи існуючий порядок Fast Context:

1. Незмінний Character Identity.
2. Immutable Context Epoch.
3. Growing exact conversation history.
4. Luna-managed Markdown Context.
5. Current user input.

Markdown-контекст додавай як один текстовий блок у мінливій частині prompt, після історії.

Не вставляй у нього мінливі технічні метадані, timestamps або revision IDs без потреби.

**Ключове правило – редагування Markdown-контексту не повинно змінювати стабільний префікс Fast prompt.**

Збережи локальний точний tokenizer, єдиний BOS, input/output reserve, stateless `/v1/completions`, streaming і cancellation.

Контекст може регулярно наближатися до 16K, тому не резервуй більшу його частину під Suggested Threads. Використовуй розумний невеликий token budget для робочого Markdown.

## 5. Compaction залишається за Luna

Не замінюй механізм Context Epochs одним великим Markdown-файлом.

Luna й надалі відповідає за семантичне стиснення історії:

- Асинхронна підготовка на 75% бюджету.
- Атомарне перемикання Context Epoch.
- Збереження точних нових повідомлень.
- Детермінований fallback після 90%.

Markdown Context – це **актуальна робоча перспектива Luna**, а Context Epoch – стиснена історична основа Fast.

Luna може відновлювати забуті Fast деталі зі свого ширшого контексту, але не повинна вигадувати спогади.

## 6. Поведінка персонажа

Luna може прямо впливати на те, що Nemotron скаже.

Наприклад, запропонувати:

> If the user brings up losing again, say something like: "At this point you should probably uninstall the game."

Це необов'язкова поведінкова ідея, а не команда.

Nemotron повинен залишатися природним співрозмовником: імпровізувати, іноді ігнорувати підказки, жартувати, сперечатися й не перетворюватися на шаблонного асистента.

Актуальні виправлення та обмеження користувача мають перевагу над старими Suggested Threads. Оновлення Luna, яке запізнилося, не повинно повертати вже скасовану поведінку.

## 7. Перевірка

Виконай реальні діалоги з Nemotron і Luna:

- Luna створює конкретний Suggested Thread, який природно впливає на наступну відповідь Fast.
- Luna оновлює або видаляє застарілу ідею.
- Після прохання припинити жарти попередня жартівлива підказка більше не застосовується.
- Luna не змінює контекст, коли немає нічого корисного.
- Зміни контексту не блокують Fast.
- Markdown Context переживає перезапуск.
- Compaction продовжує працювати біля 16K.

Окремо перевір KV cache: порівняй кількість переобчислених prompt tokens при оновленні Markdown і при перемиканні Context Epoch. Не роби висновків про кеш лише з TTFT.

Не додавай десятки тестів заради покриття. Перевір критичні інваріанти й реальну поведінку.

## 8. Завершення

Онови відповідні `AGENTS.md`, README та документацію. Створи `docs/M4_2_IMPLEMENTATION.md`.

У звіті покажи:

- Як Luna редагує Markdown Context.
- Як він зберігається та потрапляє в Fast prompt.
- Приклади реальних змін і відповідей Nemotron.
- Вплив на KV cache та TTFT.
- Сумісність із Context Epochs і старими SQLite-базами.
- Що вдалося спростити порівняно з M4.1.

Працюй в окремій гілці від `main`, створи один змістовний коміт з автором softsock і потрібним `Co-authored-by`. Не створюй PR і не пуш без окремого прохання.

## Definition of Done

**Luna асинхронно керує одним зрозумілим Markdown-контекстом, а Nemotron використовує його для природної розмови.**

Немає окремого Attention Engine чи Beat Scheduler. Існуючі Journal, Context Epochs, KV-cache-оптимізація, streaming і незалежність Fast залишаються працездатними.

Головний критерій – не складність системи, а помітний, доречний вплив Luna на характер і репліки Nemotron.