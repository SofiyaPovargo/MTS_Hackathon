"""Generate the gold-labeled dataset for commitment extraction research.

Writes research/data/gold/<id>.json and research/data/manifest.json.
Timestamps are placeholder estimates (chars/sec); they will be refreshed
from actual TTS synthesis in 01_data_synth.ipynb.
"""
from __future__ import annotations

import json
import sys
from datetime import date, time
from decimal import Decimal
from pathlib import Path

from schemas import (
    Commitment,
    CommitmentStatus,
    CommitmentType,
    DialogueTurn,
    ExpectedCommitment,
    GoldCase,
    Owner,
)

DATA_DIR = Path(__file__).resolve().parent / "data"
GOLD_DIR = DATA_DIR / "gold"

CHARS_PER_SEC = 12.0
MIN_TURN_SEC = 1.0
PAUSE_SEC = 0.4

CONV_DATE = date(2026, 10, 5)  # понедельник
TZ = "Europe/Moscow"


def q(speaker: str, text: str, index: int) -> tuple[DialogueTurn, int]:
    return DialogueTurn(speaker=speaker, text=text), index


# --------------------------------------------------------------------------
# Сценарии: (id, category, participants, turns, expected, notes)
# --------------------------------------------------------------------------

CASES: list[GoldCase] = [
    GoldCase(
        id="explicit_deadline_01",
        category="explicit_deadline",
        conversation_date=CONV_DATE,
        user_timezone=TZ,
        participants={"operator": "Анна (менеджер клиники)", "client": "Игорь Владимирович"},
        dialogue=[
            DialogueTurn(speaker="operator", text="Здравствуйте, Игорь Владимирович! Я Анна из клиники «Восстановление», по поводу вашего курса реабилитации."),
            DialogueTurn(speaker="client", text="Здравствуйте, Анна. Да, я вас внимательно слушаю."),
            DialogueTurn(speaker="operator", text="Мы подготовили для вас договор, я пришлю его до пятницы удобным вам способом."),
            DialogueTurn(speaker="client", text="Хорошо, буду ждать. Спасибо!"),
        ],
        expected_commitments=[
            ExpectedCommitment(
                turn_index=2,
                type=CommitmentType.promise,
                title="Менеджер пришлёт договор на реабилитацию",
                owner=Owner.counterparty,
                due_date=date(2026, 10, 9),
            ),
        ],
        notes="Явный дедлайн «до пятницы» (09.10). Время не указано.",
    ),
    GoldCase(
        id="meeting_02",
        category="meeting_with_time",
        conversation_date=CONV_DATE,
        user_timezone=TZ,
        participants={"operator": "Алексей (банк)", "client": "клиент"},
        dialogue=[
            DialogueTurn(speaker="operator", text="Добрый день! Алексей из банка, по вашей заявке на кредит."),
            DialogueTurn(speaker="client", text="Добрый день, да, слушаю."),
            DialogueTurn(speaker="operator", text="Нам нужно созвониться для уточнения деталей. Предлагаю во вторник в пятнадцать ноль-ноль."),
            DialogueTurn(speaker="client", text="Вторник в три часа дня мне подходит."),
            DialogueTurn(speaker="operator", text="Отлично, тогда созваниваемся во вторник в пятнадцать ноль-ноль."),
        ],
        expected_commitments=[
            ExpectedCommitment(
                turn_index=2,
                type=CommitmentType.meeting,
                title="Созвон для уточнения деталей по кредиту",
                owner=Owner.user,
                due_date=date(2026, 10, 6),
                due_time=time(15, 0),
            ),
        ],
        notes="Встреча с точным временем: вторник 06.10 в 15:00.",
    ),
    GoldCase(
        id="payment_03",
        category="payment_with_date",
        conversation_date=CONV_DATE,
        user_timezone=TZ,
        participants={"operator": "мастер (ремонт техники)", "client": "клиент"},
        dialogue=[
            DialogueTurn(speaker="client", text="Здравствуйте, это ремонт техники? Вопрос по оплате за ремонт холодильника."),
            DialogueTurn(speaker="operator", text="Да, здравствуйте. Ремонт завершён, стоимость — четыре тысячи рублей."),
            DialogueTurn(speaker="client", text="Когда нужно оплатить?"),
            DialogueTurn(speaker="operator", text="Оплату можно внести до двадцатого числа, наличными или переводом."),
            DialogueTurn(speaker="client", text="Хорошо, оплачу до двадцатого."),
        ],
        expected_commitments=[
            ExpectedCommitment(
                turn_index=3,
                type=CommitmentType.payment,
                title="Оплата ремонта холодильника 4000 рублей",
                owner=Owner.user,
                due_date=date(2026, 10, 20),
                amount=Decimal(4000),
                currency="RUB",
            ),
        ],
        notes="Платёж с датой «до 20 числа» (20.10).",
    ),
    GoldCase(
        id="ambiguous_04",
        category="ambiguous",
        conversation_date=CONV_DATE,
        user_timezone=TZ,
        participants={"operator": "типография", "client": "клиент"},
        dialogue=[
            DialogueTurn(speaker="client", text="Здравствуйте, когда будет готов мой заказ на печать визиток?"),
            DialogueTurn(speaker="operator", text="Здравствуйте! Постараемся сделать быстро, как только напечатаем — сразу сообщим."),
            DialogueTurn(speaker="client", text="Мне бы хотя бы примерно знать срок."),
            DialogueTurn(speaker="operator", text="Точный срок пока назвать не могу, наберём вас."),
        ],
        expected_commitments=[
            ExpectedCommitment(
                turn_index=1,
                type=CommitmentType.promise,
                title="Готовность заказа визиток",
                owner=Owner.counterparty,
                status=CommitmentStatus.needs_clarification,
                uncertainty=["нет конкретной даты или срока — только «быстро»"],
            ),
        ],
        notes="Тест-кейс из скилла: «постараемся сделать быстро» → needs_clarification.",
    ),
    GoldCase(
        id="contradictory_05",
        category="contradictory_dates",
        conversation_date=CONV_DATE,
        user_timezone=TZ,
        participants={"operator": "транспортная компания", "client": "клиент"},
        dialogue=[
            DialogueTurn(speaker="client", text="Здравствуйте, по моей накладной когда будет доставка?"),
            DialogueTurn(speaker="operator", text="Добрый день! Доставка завтра, то есть к пятнице к двенадцати."),
            DialogueTurn(speaker="client", text="Но сегодня уже пятница."),
            DialogueTurn(speaker="operator", text="Ой, прошу прощения. Значит, доставка завтра, в субботу."),
        ],
        expected_commitments=[
            ExpectedCommitment(
                turn_index=1,
                type=CommitmentType.deadline,
                title="Доставка груза по накладной",
                owner=Owner.counterparty,
                status=CommitmentStatus.needs_clarification,
                uncertainty=["противоречивые даты: «завтра», «пятница», «суббота»"],
            ),
        ],
        notes="Тест-кейс из скилла: противоречивые даты → needs_clarification.",
    ),
    GoldCase(
        id="no_commitment_06",
        category="no_commitment",
        conversation_date=CONV_DATE,
        user_timezone=TZ,
        participants={"operator": "автосервис", "client": "клиент"},
        dialogue=[
            DialogueTurn(speaker="operator", text="Автосервис «Форсаж», здравствуйте."),
            DialogueTurn(speaker="client", text="Здравствуйте, я хотел узнать, готова ли машина."),
            DialogueTurn(speaker="operator", text="Да, работа завершена, можете забирать."),
            DialogueTurn(speaker="client", text="Отлично, спасибо за информацию!"),
            DialogueTurn(speaker="operator", text="Всего доброго!"),
        ],
        expected_commitments=[],
        notes="Тест-кейс из скилла: договорённостей нет.",
    ),
    GoldCase(
        id="follow_up_07",
        category="follow_up",
        conversation_date=CONV_DATE,
        user_timezone=TZ,
        participants={"operator": "бухгалтерия", "client": "Наталья Петровна"},
        dialogue=[
            DialogueTurn(speaker="operator", text="Здравствуйте, Наталья Петровна, это бухгалтерия компании «Ромашка»."),
            DialogueTurn(speaker="client", text="Здравствуйте, я вас слушаю."),
            DialogueTurn(speaker="operator", text="По вашему вопросу о документах я перезвоню вам в четверг после обеда."),
            DialogueTurn(speaker="client", text="Хорошо, буду ждать звонка."),
        ],
        expected_commitments=[
            ExpectedCommitment(
                turn_index=2,
                type=CommitmentType.follow_up,
                title="Перезвон по вопросу документов",
                owner=Owner.counterparty,
                due_date=date(2026, 10, 8),
            ),
        ],
        notes="Follow-up с датой «в четверг» (08.10), время расплывчатое — оставляем без времени.",
    ),
    GoldCase(
        id="payment_advance_08",
        category="payment_amount",
        conversation_date=CONV_DATE,
        user_timezone=TZ,
        participants={"operator": "ремонтно-строительная бригада", "client": "клиент"},
        dialogue=[
            DialogueTurn(speaker="client", text="Добрый день, это по ремонту квартиры. Сколько стартовый платёж?"),
            DialogueTurn(speaker="operator", text="Здравствуйте. Аванс — пятнадцать тысяч рублей, переведите до среды."),
            DialogueTurn(speaker="client", text="Окей, переведу аванс до среды."),
        ],
        expected_commitments=[
            ExpectedCommitment(
                turn_index=1,
                type=CommitmentType.payment,
                title="Аванс за ремонт квартиры 15000 рублей",
                owner=Owner.user,
                due_date=date(2026, 10, 7),
                amount=Decimal(15000),
                currency="RUB",
            ),
        ],
        notes="Платёж с суммой 15 000 руб. и датой «до среды» (07.10).",
    ),
    GoldCase(
        id="deadline_month_end_09",
        category="deadline",
        conversation_date=CONV_DATE,
        user_timezone=TZ,
        participants={"operator": "подрядчик", "client": "заказчик"},
        dialogue=[
            DialogueTurn(speaker="client", text="Когда сдадите отчётные документы?"),
            DialogueTurn(speaker="operator", text="Документы будут готовы, мы сдадим их до конца месяца."),
            DialogueTurn(speaker="client", text="Понял, ждём."),
        ],
        expected_commitments=[
            ExpectedCommitment(
                turn_index=1,
                type=CommitmentType.deadline,
                title="Сдача отчётных документов",
                owner=Owner.counterparty,
                due_date=date(2026, 10, 31),
            ),
        ],
        notes="«До конца месяца» резолвится в 31.10.",
    ),
    GoldCase(
        id="meeting_office_10",
        category="meeting_with_time",
        conversation_date=CONV_DATE,
        user_timezone=TZ,
        participants={"operator": "офис продаж", "client": "клиент"},
        dialogue=[
            DialogueTurn(speaker="operator", text="Здравствуйте! Это офис продаж. Предлагаю встретиться у нас в офисе, обсудим условия."),
            DialogueTurn(speaker="client", text="Когда вам удобно?"),
            DialogueTurn(speaker="operator", text="Давайте в пятницу в десять утра."),
            DialogueTurn(speaker="client", text="В пятницу в десять утра подходит, приеду."),
        ],
        expected_commitments=[
            ExpectedCommitment(
                turn_index=2,
                type=CommitmentType.meeting,
                title="Встреча в офисе для обсуждения условий",
                owner=Owner.user,
                due_date=date(2026, 10, 9),
                due_time=time(10, 0),
            ),
        ],
        notes="Встреча «в пятницу в 10 утра» (09.10 10:00).",
    ),
    GoldCase(
        id="multiple_11",
        category="multiple_commitments",
        conversation_date=CONV_DATE,
        user_timezone=TZ,
        participants={"operator": "Ольга (ТехноПоставка)", "client": "закупщик"},
        dialogue=[
            DialogueTurn(speaker="operator", text="Алло, добрый день! Менеджер Ольга, компания «ТехноПоставка», по вашему заказу на серверы."),
            DialogueTurn(speaker="client", text="Здравствуйте, да."),
            DialogueTurn(speaker="operator", text="Договор пришлю завтра до конца дня."),
            DialogueTurn(speaker="client", text="Хорошо. И ещё перезвоните мне после обеда."),
            DialogueTurn(speaker="operator", text="Обязательно перезвоню. А аванс — пятьдесят тысяч, нужно внести до встречи."),
            DialogueTurn(speaker="client", text="Записал, аванс внесём."),
        ],
        expected_commitments=[
            ExpectedCommitment(
                turn_index=2,
                type=CommitmentType.promise,
                title="Договор на поставку серверов",
                owner=Owner.counterparty,
                due_date=date(2026, 10, 6),
            ),
            ExpectedCommitment(
                turn_index=3,
                type=CommitmentType.follow_up,
                title="Перезвон после обеда",
                owner=Owner.counterparty,
                due_date=date(2026, 10, 6),
            ),
            ExpectedCommitment(
                turn_index=4,
                type=CommitmentType.payment,
                title="Аванс 50000 рублей за серверы",
                owner=Owner.user,
                amount=Decimal(50000),
                currency="RUB",
                status=CommitmentStatus.needs_clarification,
                uncertainty=["дата аванса не определена — только «до встречи»"],
            ),
        ],
        notes="Несколько договорённостей в одном разговоре (проверка множественного извлечения).",
    ),
    GoldCase(
        id="open_question_12",
        category="open_question",
        conversation_date=CONV_DATE,
        user_timezone=TZ,
        participants={"operator": "транспортная компания", "client": "клиент"},
        dialogue=[
            DialogueTurn(speaker="client", text="Здравствуйте, а можно возить оборудование с холодильниками?"),
            DialogueTurn(speaker="operator", text="Нужно уточнить у юриста, я перезвоню вам."),
            DialogueTurn(speaker="client", text="Хорошо."),
        ],
        expected_commitments=[
            ExpectedCommitment(
                turn_index=1,
                type=CommitmentType.open_question,
                title="Допустимость перевозки оборудования с температурным режимом",
                owner=Owner.counterparty,
                status=CommitmentStatus.needs_clarification,
                uncertainty=["вопрос не решён, ответа пока нет"],
            ),
        ],
        notes="Открытый вопрос без ответа → needs_clarification.",
    ),
    GoldCase(
        id="proposal_13",
        category="proposal_not_confirmed",
        conversation_date=CONV_DATE,
        user_timezone=TZ,
        participants={"operator": "отдел продаж", "client": "клиент"},
        dialogue=[
            DialogueTurn(speaker="operator", text="Добрый день! Мы могли бы сделать вам скидку десять процентов, если вы оплатите сразу."),
            DialogueTurn(speaker="client", text="Мне нужно подумать."),
            DialogueTurn(speaker="operator", text="Конечно, без спешки."),
        ],
        expected_commitments=[
            ExpectedCommitment(
                turn_index=0,
                type=CommitmentType.payment,
                title="Скидка 10% при оплате сразу",
                owner=Owner.unknown,
                status=CommitmentStatus.needs_clarification,
                uncertainty=["предложение, а не подтверждённое соглашение", "не указаны дата и сумма"],
            ),
        ],
        notes="Тест-кейс из скилла: отделять предложение от подтверждённого соглашения.",
    ),
    GoldCase(
        id="delivery_payment_14",
        category="payment_amount",
        conversation_date=CONV_DATE,
        user_timezone=TZ,
        participants={"operator": "курьерская служба", "client": "клиент"},
        dialogue=[
            DialogueTurn(speaker="operator", text="Здравствуйте! Курьерская служба, по поводу доставки вашего заказа."),
            DialogueTurn(speaker="client", text="Здравствуйте, сколько будет стоить доставка?"),
            DialogueTurn(speaker="operator", text="Доставка — пятьсот рублей, оплатите при получении."),
            DialogueTurn(speaker="client", text="Отлично, договорились."),
        ],
        expected_commitments=[
            ExpectedCommitment(
                turn_index=2,
                type=CommitmentType.payment,
                title="Оплата доставки заказа 500 рублей",
                owner=Owner.user,
                amount=Decimal(500),
                currency="RUB",
                status=CommitmentStatus.needs_clarification,
                uncertainty=["не указан срок оплаты — только «при получении»"],
            ),
        ],
        notes="Сумма известна, даты нет → needs_clarification по сроку.",
    ),
]


def build_timestamps(dialogue: list[DialogueTurn]) -> list[tuple[DialogueTurn, float, float]]:
    """Placeholder-таймстампы по длине текста. Заменятся реальными после синтеза."""
    out: list[tuple[DialogueTurn, float, float]] = []
    t = 0.0
    for turn in dialogue:
        start = t
        dur = max(len(turn.text) / CHARS_PER_SEC, MIN_TURN_SEC) + PAUSE_SEC
        out.append((turn, round(start, 2), round(start + dur, 2)))
        t += dur + PAUSE_SEC
    return out


def to_commitment(exp: ExpectedCommitment, quoted: tuple[float, float], quote: str) -> Commitment:
    return Commitment(
        type=exp.type,
        title=exp.title,
        owner=exp.owner,
        due_date=exp.due_date,
        due_time=exp.due_time,
        amount=exp.amount,
        currency=exp.currency,
        context_quote=quote,
        audio_start=quoted[0],
        audio_end=quoted[1],
        status=exp.status,
        uncertainty=exp.uncertainty,
    )


def serialize(case: GoldCase) -> dict:
    segs = build_timestamps(case.dialogue)
    commitment_list = []
    for exp in case.expected_commitments:
        turn, start, end = segs[exp.turn_index]
        commitment_list.append(
            to_commitment(exp, (start, end), turn.text).model_dump(mode="json")
        )
    return {
        "id": case.id,
        "category": case.category,
        "conversation_date": case.conversation_date.isoformat(),
        "user_timezone": case.user_timezone,
        "participants": case.participants,
        "dialogue": [
            {"speaker": tr.speaker, "text": tr.text, "start": s, "end": e}
            for tr, s, e in segs
        ],
        "expected_commitments": commitment_list,
        "notes": case.notes,
    }


def _main() -> None:
    GOLD_DIR.mkdir(parents=True, exist_ok=True)
    manifest = []
    for case in CASES:
        payload = serialize(case)
        (GOLD_DIR / f"{case.id}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        manifest.append(
            {
                "id": case.id,
                "category": case.category,
                "num_commitments": len(case.expected_commitments),
                "split": "eval",
            }
        )
        print(f"  {case.id:28s} {case.category:24s} -> {len(case.expected_commitments)} commitments")
    (DATA_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Wrote {len(manifest)} cases to {GOLD_DIR}")


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    _main()