import asyncio
from datetime import datetime
from random import shuffle

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    KeyboardButton,
    Contact,
)

from sqlalchemy import and_, func, select

from .bot_states import TestStates, RegistrationStates, AdminStates
from .config import settings
from .db import get_session, init_db
from .models import (
    TestDirection,
    TestQuestion,
    TestSession,
    TestStatus,
    User,
    UserRole,
    Word,
    WordList,
)


bot = Bot(
    token=settings.bot_token,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()


CEFR_LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"]


async def get_or_create_user(tg_user, role_hint: UserRole | None = None) -> User:
    async for session in get_session():
        stmt = select(User).where(User.telegram_id == tg_user.id)
        user = await session.scalar(stmt)
        if user:
            return user  # type: ignore[return-value]

        role = UserRole.STUDENT
        if tg_user.id in settings.admin_ids:
            role = UserRole.ADMIN
        elif role_hint:
            role = role_hint

        user = User(
            telegram_id=tg_user.id,
            username=tg_user.username,
            full_name=tg_user.full_name,
            role=role,
            is_registered=(role != UserRole.STUDENT),  # Admin/Teacher auto-registered
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


def build_levels_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text=level, callback_data=f"level:{level}")
            for level in CEFR_LEVELS[:3]
        ],
        [
            InlineKeyboardButton(text=level, callback_data=f"level:{level}")
            for level in CEFR_LEVELS[3:]
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_direction_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Turkish ➜ Uzbek", callback_data="dir:tr_to_uz"
                )
            ],
            [
                InlineKeyboardButton(
                    text="Uzbek ➜ Turkish", callback_data="dir:uz_to_tr"
                )
            ],
        ]
    )


def build_count_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="10", callback_data="count:10"),
                InlineKeyboardButton(text="20", callback_data="count:20"),
            ],
            [
                InlineKeyboardButton(text="50", callback_data="count:50"),
                InlineKeyboardButton(text="All", callback_data="count:all"),
            ],
        ]
    )


def build_answer_controls() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Skip", callback_data="q:skip"),
                InlineKeyboardButton(text="No answer", callback_data="q:no_answer"),
            ],
            [
                InlineKeyboardButton(text="Finish test", callback_data="q:finish"),
            ],
        ]
    )


@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    user = await get_or_create_user(message.from_user)
    
    # Check if student needs registration
    if user.role == UserRole.STUDENT and not user.is_registered:
        await state.set_state(RegistrationStates.waiting_first_name)
        await message.answer(
            "Salom! Ro'yxatdan o'tish uchun quyidagi ma'lumotlarni kiriting.\n\n"
            "Ismingizni kiriting:"
        )
        return
    
    # Admin/Teacher or already registered student
    if user.role == UserRole.ADMIN:
        text = (
            "Salom, Admin! Bot boshqaruv buyruqlari:\n"
            "/view_results - O'quvchilar natijalarini ko'rish\n"
            "/add_teacher - O'qituvchi qo'shish"
        )
    elif user.role == UserRole.TEACHER:
        text = (
            "Salom, O'qituvchi! Bot buyruqlari:\n"
            "/view_results - O'quvchilar natijalarini ko'rish\n"
            "/upload_words - So'zlar yuklash"
        )
    else:
        text = (
            "Salom! Men turkcha–o'zbekcha so'zlarni o'rganish uchun botman.\n\n"
            "Testni boshlash: /start_test"
        )
    await message.answer(text)


# ========== REGISTRATION HANDLERS ==========

@dp.message(RegistrationStates.waiting_first_name)
async def handle_first_name(message: Message, state: FSMContext) -> None:
    first_name = message.text.strip() if message.text else ""
    if not first_name or len(first_name) < 2:
        await message.answer("Iltimos, to'g'ri ism kiriting (kamida 2 belgi):")
        return
    
    await state.update_data(first_name=first_name)
    await state.set_state(RegistrationStates.waiting_last_name)
    await message.answer("Familiyangizni kiriting:")


@dp.message(RegistrationStates.waiting_last_name)
async def handle_last_name(message: Message, state: FSMContext) -> None:
    last_name = message.text.strip() if message.text else ""
    if not last_name or len(last_name) < 2:
        await message.answer("Iltimos, to'g'ri familiya kiriting (kamida 2 belgi):")
        return
    
    await state.update_data(last_name=last_name)
    await state.set_state(RegistrationStates.waiting_phone)
    
    phone_keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Telefon raqamni yuborish", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    await message.answer(
        "Telefon raqamingizni yuboring (yoki tugmani bosing):",
        reply_markup=phone_keyboard
    )


@dp.message(RegistrationStates.waiting_phone, F.contact)
async def handle_phone_contact(message: Message, state: FSMContext) -> None:
    contact: Contact = message.contact
    phone = contact.phone_number
    await state.update_data(phone_number=phone)
    await state.set_state(RegistrationStates.choosing_cefr)
    await message.answer(
        "Telefon raqam qabul qilindi!\n\n"
        "Qaysi CEFR darajasini tanlaysiz?",
        reply_markup=ReplyKeyboardRemove()
    )
    await message.answer(
        "CEFR darajasini tanlang:",
        reply_markup=build_levels_keyboard()
    )


@dp.message(RegistrationStates.waiting_phone)
async def handle_phone_text(message: Message, state: FSMContext) -> None:
    phone = message.text.strip() if message.text else ""
    # Basic phone validation
    if not phone or len(phone) < 9:
        await message.answer("Iltimos, to'g'ri telefon raqam kiriting yoki tugmani bosing:")
        return
    
    await state.update_data(phone_number=phone)
    await state.set_state(RegistrationStates.choosing_cefr)
    await message.answer(
        "Telefon raqam qabul qilindi!\n\n"
        "Qaysi CEFR darajasini tanlaysiz?",
        reply_markup=build_levels_keyboard()
    )


@dp.callback_query(RegistrationStates.choosing_cefr, F.data.startswith("level:"))
async def reg_choose_cefr(callback: CallbackQuery, state: FSMContext) -> None:
    level = callback.data.split(":", 1)[1]
    await state.update_data(cefr_level=level)
    await state.set_state(RegistrationStates.choosing_direction)
    await callback.message.edit_text(
        f"CEFR daraja: <b>{level}</b>\nYo'nalishni tanlang:",
        reply_markup=build_direction_keyboard()
    )
    await callback.answer()


@dp.callback_query(RegistrationStates.choosing_direction, F.data.startswith("dir:"))
async def reg_choose_direction(callback: CallbackQuery, state: FSMContext) -> None:
    raw = callback.data.split(":", 1)[1]
    direction = TestDirection.TR_TO_UZ if raw == "tr_to_uz" else TestDirection.UZ_TO_TR
    
    data = await state.get_data()
    first_name = data.get("first_name")
    last_name = data.get("last_name")
    phone_number = data.get("phone_number")
    cefr_level = data.get("cefr_level")
    
    if not all([first_name, last_name, phone_number, cefr_level]):
        await callback.answer("Xatolik: ma'lumotlar to'liq emas.", show_alert=True)
        return
    
    # Save registration data
    user = await get_or_create_user(callback.from_user)
    async for session in get_session():
        user.first_name = first_name
        user.last_name = last_name
        user.phone_number = phone_number
        user.preferred_cefr_level = cefr_level
        user.preferred_direction = direction
        user.is_registered = True
        await session.commit()
    
    await state.clear()
    await callback.message.edit_text(
        f"✅ Ro'yxatdan o'tdingiz!\n\n"
        f"Ism: <b>{first_name} {last_name}</b>\n"
        f"Telefon: <b>{phone_number}</b>\n"
        f"CEFR daraja: <b>{cefr_level}</b>\n"
        f"Yo'nalish: <b>{'TR➜UZ' if direction == TestDirection.TR_TO_UZ else 'UZ➜TR'}</b>\n\n"
        f"Testni boshlash: /start_test"
    )
    await callback.answer()


# ========== TEST HANDLERS ==========

@dp.message(Command("start_test"))
async def cmd_start_test(message: Message, state: FSMContext) -> None:
    user = await get_or_create_user(message.from_user)
    
    # Check if student is registered
    if user.role == UserRole.STUDENT and not user.is_registered:
        await message.answer("Iltimos, avval ro'yxatdan o'ting: /start")
        return
    
    await state.clear()
    await state.set_state(TestStates.choosing_level)
    await message.answer(
        "Qaysi CEFR darajasida test qilamiz?", reply_markup=build_levels_keyboard()
    )


@dp.callback_query(TestStates.choosing_level, F.data.startswith("level:"))
async def choose_level(callback: CallbackQuery, state: FSMContext) -> None:
    level = callback.data.split(":", 1)[1]
    await state.update_data(level=level)
    await state.set_state(TestStates.choosing_direction)
    await callback.message.edit_text(
        f"Daraja: <b>{level}</b>\nYo‘nalishni tanlang:",
        reply_markup=build_direction_keyboard(),
    )
    await callback.answer()


@dp.callback_query(TestStates.choosing_direction, F.data.startswith("dir:"))
async def choose_direction(callback: CallbackQuery, state: FSMContext) -> None:
    raw = callback.data.split(":", 1)[1]
    direction = TestDirection.TR_TO_UZ if raw == "tr_to_uz" else TestDirection.UZ_TO_TR
    await state.update_data(direction=direction.value)
    data = await state.get_data()
    level = data.get("level", "")
    await state.set_state(TestStates.choosing_count)
    await callback.message.edit_text(
        f"Daraja: <b>{level}</b>\nYo‘nalish: <b>{'TR➜UZ' if direction == TestDirection.TR_TO_UZ else 'UZ➜TR'}</b>\n"
        "Necha ta savol bo‘lsin?",
        reply_markup=build_count_keyboard(),
    )
    await callback.answer()


async def _create_test_session_for_user(
    user: User, level: str, direction: TestDirection, count: int | None
) -> TestSession | None:
    async for session in get_session():
        # Select all words for this level
        stmt = (
            select(Word)
            .join(WordList)
            .where(WordList.cefr_level == level)
        )
        words_result = await session.scalars(stmt)
        words = list(words_result.all())

        if not words:
            return None

        shuffle(words)
        if count is not None:
            words = words[:count]

        test_session = TestSession(
            student_id=user.id,
            cefr_level=level,
            direction=direction,
            total_questions=len(words),
        )
        session.add(test_session)
        await session.flush()

        questions: list[TestQuestion] = []
        for idx, w in enumerate(words, start=1):
            if direction == TestDirection.TR_TO_UZ:
                shown_lang = "tr"
                correct_answer = w.uzbek
            else:
                shown_lang = "uz"
                correct_answer = w.turkish
            q = TestQuestion(
                test_session_id=test_session.id,
                word_id=w.id,
                shown_lang=shown_lang,
                correct_answer=correct_answer,
                position=idx,
            )
            questions.append(q)
        session.add_all(questions)
        await session.commit()
        await session.refresh(test_session)
        return test_session


@dp.callback_query(TestStates.choosing_count, F.data.startswith("count:"))
async def choose_count(callback: CallbackQuery, state: FSMContext) -> None:
    raw_count = callback.data.split(":", 1)[1]
    data = await state.get_data()
    level = data.get("level")
    direction_val = data.get("direction")
    if not level or not direction_val:
        await callback.answer("Xatolik: ma'lumot yetarli emas.", show_alert=True)
        return

    direction = TestDirection(direction_val)
    count: int | None
    if raw_count == "all":
        count = None
    else:
        count = int(raw_count)

    user = await get_or_create_user(callback.from_user)
    test_session = await _create_test_session_for_user(user, level, direction, count)
    if not test_session:
        await callback.message.edit_text(
            f"Bu darajada ({level}) hali so‘zlar yuklanmagan. O‘qituvchidan so‘zlar qo‘shishni so‘rang."
        )
        await state.clear()
        await callback.answer()
        return

    await state.update_data(test_session_id=test_session.id, current_pos=1)
    await state.set_state(TestStates.answering)
    await callback.answer()
    await _send_question(callback.message, state)


async def _send_question(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    test_session_id = data.get("test_session_id")
    current_pos = data.get("current_pos", 1)
    if not test_session_id:
        await message.answer("Xatolik: test topilmadi.")
        await state.clear()
        return

    async for session in get_session():
        stmt = select(TestQuestion).where(
            TestQuestion.test_session_id == test_session_id,
            TestQuestion.position == current_pos,
        )
        q = await session.scalar(stmt)
        if not q:
            # No more questions, show results
            await _finish_test_and_show_result(message, test_session_id, state)
            return

        word = await session.get(Word, q.word_id)
        if not word:
            await message.answer("Xatolik: so‘z topilmadi.")
            return

        if q.shown_lang == "tr":
            text = f"#{current_pos}. Turkcha so‘z: <b>{word.turkish}</b>\nJavob sifatida o‘zbekcha tarjimasini yozing."
        else:
            text = f"#{current_pos}. O‘zbekcha so‘z: <b>{word.uzbek}</b>\nJavob sifatida turkcha tarjimasini yozing."

        await message.answer(text, reply_markup=build_answer_controls())


@dp.message(TestStates.answering)
async def handle_answer(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    test_session_id = data.get("test_session_id")
    current_pos = data.get("current_pos", 1)
    if not test_session_id:
        await message.answer("Xatolik: test topilmadi.")
        await state.clear()
        return

    answer_text = (message.text or "").strip()
    async for session in get_session():
        stmt = select(TestQuestion).where(
            TestQuestion.test_session_id == test_session_id,
            TestQuestion.position == current_pos,
        )
        q = await session.scalar(stmt)
        if not q:
            await message.answer("Savol topilmadi.")
            return

        q.student_answer = answer_text
        q.is_correct = (
            answer_text.lower().strip() == q.correct_answer.lower().strip()
            if answer_text
            else False
        )
        await session.commit()

    await state.update_data(current_pos=current_pos + 1)
    await _send_question(message, state)


@dp.callback_query(TestStates.answering, F.data.startswith("q:"))
async def handle_answer_controls(callback: CallbackQuery, state: FSMContext) -> None:
    action = callback.data.split(":", 1)[1]
    data = await state.get_data()
    test_session_id = data.get("test_session_id")
    current_pos = data.get("current_pos", 1)
    if not test_session_id:
        await callback.answer("Xatolik: test topilmadi.", show_alert=True)
        await state.clear()
        return

    async for session in get_session():
        stmt = select(TestQuestion).where(
            TestQuestion.test_session_id == test_session_id,
            TestQuestion.position == current_pos,
        )
        q = await session.scalar(stmt)
        if not q:
            await callback.answer("Savol topilmadi.", show_alert=True)
            return

        if action == "skip":
            q.skipped = True
            await session.commit()
            # Move to next question, and skipped will be asked at the end
            await state.update_data(current_pos=current_pos + 1)
            await callback.answer("Savol keyinga qoldirildi.")
            await _send_question(callback.message, state)
            return

        if action == "no_answer":
            q.student_answer = ""
            q.is_correct = False
            await session.commit()
            await state.update_data(current_pos=current_pos + 1)
            await callback.answer("Javobsiz deb belgilandi.")
            await _send_question(callback.message, state)
            return

        if action == "finish":
            await _finish_test_and_show_result(callback.message, test_session_id, state)
            await callback.answer("Test yakunlandi.")
            return


async def _finish_test_and_show_result(
    message: Message, test_session_id: int, state: FSMContext
) -> None:
    async for session in get_session():
        test_session = await session.get(TestSession, test_session_id)
        if not test_session:
            await message.answer("Test topilmadi.")
            await state.clear()
            return

        # If there are skipped questions not answered, re-ask them:
        skipped_stmt = select(TestQuestion).where(
            TestQuestion.test_session_id == test_session_id,
            TestQuestion.skipped.is_(True),
            TestQuestion.student_answer.is_(None),
        )
        skipped_not_answered = (await session.scalars(skipped_stmt)).all()

        if skipped_not_answered:
            # Move to the first skipped question
            first_skipped = skipped_not_answered[0]
            await state.update_data(current_pos=first_skipped.position)
            await message.answer(
                "Avval o‘tkazib yuborilgan savollar bor. Ularni yakunlaymiz."
            )
            await _send_question(message, state)
            return

        # All questions are either answered or explicitly no-answer
        questions_stmt = select(TestQuestion).where(
            TestQuestion.test_session_id == test_session_id
        )
        questions = (await session.scalars(questions_stmt)).all()

        correct = sum(1 for q in questions if q.is_correct)
        total = len(questions)
        no_answer = sum(
            1 for q in questions if (q.student_answer == "" or q.student_answer is None)
        )
        percent = int((correct / total) * 100) if total else 0

        test_session.status = TestStatus.FINISHED
        test_session.finished_at = datetime.utcnow()
        await session.commit()

        await state.clear()

        text = (
            f"Test yakunlandi!\n\n"
            f"Umumiy savollar: <b>{total}</b>\n"
            f"To‘g‘ri javoblar: <b>{correct}</b>\n"
            f"Javobsiz (yo‘q / bo‘sh): <b>{no_answer}</b>\n"
            f"Natija: <b>{percent}%</b>"
        )
        await message.answer(text)


# ========== TEACHER/ADMIN COMMANDS ==========

def build_filter_keyboard() -> InlineKeyboardMarkup:
    """Keyboard for filtering results by day and degree"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📅 Bugun", callback_data="filter:day:today"),
                InlineKeyboardButton(text="📅 Kecha", callback_data="filter:day:yesterday"),
            ],
            [
                InlineKeyboardButton(text="📅 Bu hafta", callback_data="filter:day:week"),
                InlineKeyboardButton(text="📅 Bu oy", callback_data="filter:day:month"),
            ],
            [
                InlineKeyboardButton(text="📅 Barcha", callback_data="filter:day:all"),
            ],
            [
                InlineKeyboardButton(text="🎓 A1", callback_data="filter:degree:A1"),
                InlineKeyboardButton(text="🎓 A2", callback_data="filter:degree:A2"),
            ],
            [
                InlineKeyboardButton(text="🎓 B1", callback_data="filter:degree:B1"),
                InlineKeyboardButton(text="🎓 B2", callback_data="filter:degree:B2"),
            ],
            [
                InlineKeyboardButton(text="🎓 C1", callback_data="filter:degree:C1"),
                InlineKeyboardButton(text="🎓 C2", callback_data="filter:degree:C2"),
            ],
            [
                InlineKeyboardButton(text="🎓 Barcha darajalar", callback_data="filter:degree:all"),
            ],
            [
                InlineKeyboardButton(text="✅ Ko'rsatish", callback_data="filter:show"),
            ],
        ]
    )


@dp.message(Command("view_results"))
async def cmd_view_results(message: Message, state: FSMContext) -> None:
    user = await get_or_create_user(message.from_user)
    
    if user.role not in [UserRole.TEACHER, UserRole.ADMIN]:
        await message.answer("Bu buyruq faqat o'qituvchilar va adminlar uchun.")
        return
    
    await state.update_data(filter_day=None, filter_degree=None)
    await message.answer(
        "O'quvchilar natijalarini ko'rish.\n\n"
        "Filtrni tanlang:",
        reply_markup=build_filter_keyboard()
    )


@dp.callback_query(F.data.startswith("filter:"))
async def handle_filter(callback: CallbackQuery, state: FSMContext) -> None:
    user = await get_or_create_user(callback.from_user)
    
    if user.role not in [UserRole.TEACHER, UserRole.ADMIN]:
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    
    parts = callback.data.split(":", 2)
    if len(parts) < 2:
        await callback.answer("Xatolik.", show_alert=True)
        return
    
    filter_type = parts[1]
    data = await state.get_data()
    
    if filter_type == "day":
        day_value = parts[2] if len(parts) > 2 else "all"
        await state.update_data(filter_day=day_value)
        await callback.answer(f"Kun: {day_value}")
        return
    
    if filter_type == "degree":
        degree_value = parts[2] if len(parts) > 2 else "all"
        await state.update_data(filter_degree=degree_value)
        await callback.answer(f"Daraja: {degree_value}")
        return
    
    if filter_type == "show":
        filter_day = data.get("filter_day")
        filter_degree = data.get("filter_degree")
        
        # Build query
        async for session in get_session():
            query = (
                select(TestSession, User)
                .join(User, TestSession.student_id == User.id)
                .where(TestSession.status == TestStatus.FINISHED)
            )
            
            # Apply day filter
            if filter_day and filter_day != "all":
                today = datetime.utcnow().date()
                if filter_day == "today":
                    query = query.where(func.date(TestSession.finished_at) == today)
                elif filter_day == "yesterday":
                    from datetime import timedelta
                    yesterday = today - timedelta(days=1)
                    query = query.where(func.date(TestSession.finished_at) == yesterday)
                elif filter_day == "week":
                    from datetime import timedelta
                    week_ago = today - timedelta(days=7)
                    query = query.where(func.date(TestSession.finished_at) >= week_ago)
                elif filter_day == "month":
                    from datetime import timedelta
                    month_ago = today - timedelta(days=30)
                    query = query.where(func.date(TestSession.finished_at) >= month_ago)
            
            # Apply degree filter
            if filter_degree and filter_degree != "all":
                query = query.where(TestSession.cefr_level == filter_degree)
            
            query = query.order_by(TestSession.finished_at.desc()).limit(100)
            
            results = await session.execute(query)
            rows = results.all()
            
            if not rows:
                await callback.message.edit_text(
                    "Natijalar topilmadi.",
                    reply_markup=None
                )
                await callback.answer()
                return
            
            # Format results
            text_parts = ["📊 <b>O'quvchilar natijalari:</b>\n"]
            
            for test_session, student in rows:
                # Calculate stats
                questions_query = (
                    select(TestQuestion)
                    .where(TestQuestion.test_session_id == test_session.id)
                )
                questions_result = await session.execute(questions_query)
                questions = questions_result.scalars().all()
                
                total = len(questions)
                correct = sum(1 for q in questions if q.is_correct)
                percent = int((correct / total) * 100) if total else 0
                
                student_name = f"{student.first_name or ''} {student.last_name or ''}".strip()
                if not student_name:
                    student_name = student.full_name or f"ID: {student.telegram_id}"
                
                direction_text = "TR➜UZ" if test_session.direction == TestDirection.TR_TO_UZ else "UZ➜TR"
                finished_date = test_session.finished_at.strftime("%Y-%m-%d %H:%M") if test_session.finished_at else "N/A"
                
                text_parts.append(
                    f"\n👤 <b>{student_name}</b>\n"
                    f"📅 {finished_date}\n"
                    f"🎓 {test_session.cefr_level} | {direction_text}\n"
                    f"✅ {correct}/{total} ({percent}%)\n"
                    f"{'─' * 20}"
                )
            
            # Split into chunks if too long (Telegram limit ~4096 chars)
            full_text = "\n".join(text_parts)
            if len(full_text) > 4000:
                # Send in chunks
                chunk = ""
                for part in text_parts:
                    if len(chunk + part) > 4000:
                        await callback.message.answer(chunk)
                        chunk = part
                    else:
                        chunk += part
                if chunk:
                    await callback.message.answer(chunk)
            else:
                await callback.message.edit_text(full_text, reply_markup=None)
            
            await callback.answer()
            await state.clear()


# ========== ADMIN COMMANDS ==========

@dp.message(Command("add_teacher"))
async def cmd_add_teacher(message: Message, state: FSMContext) -> None:
    user = await get_or_create_user(message.from_user)
    
    if user.role != UserRole.ADMIN:
        await message.answer("Bu buyruq faqat adminlar uchun.")
        return
    
    # Check if replying to a message (get user from reply)
    if message.reply_to_message and message.reply_to_message.from_user:
        target_user = message.reply_to_message.from_user
        await _add_teacher_by_user(message, target_user)
        return
    
    # Check if forwarding a message (get user from forward)
    if message.forward_from:
        await _add_teacher_by_user(message, message.forward_from)
        return
    
    await state.set_state(AdminStates.waiting_teacher_username)
    await message.answer(
        "Yangi o'qituvchi qo'shish.\n\n"
        "<b>Usul 1:</b> O'qituvchining xabariga javob bering va /add_teacher yozing\n"
        "<b>Usul 2:</b> O'qituvchining xabarini forward qiling va /add_teacher yozing\n"
        "<b>Usul 3:</b> Username (@username) yoki user ID (123456789) yuboring"
    )


async def _add_teacher_by_user(message: Message, target_user) -> None:
    """Helper function to add teacher by Telegram user object."""
    teacher_id = target_user.id
    
    async for session in get_session():
        stmt = select(User).where(User.telegram_id == teacher_id)
        teacher_user = await session.scalar(stmt)
        
        if teacher_user:
            teacher_user.role = UserRole.TEACHER
            teacher_user.is_registered = True
            await session.commit()
            name = teacher_user.full_name or teacher_user.username or f"ID: {teacher_id}"
            await message.answer(
                f"✅ O'qituvchi muvaffaqiyatli qo'shildi!\n\n"
                f"Foydalanuvchi: <b>{name}</b>\n"
                f"Username: @{target_user.username or 'yo\'q'}\n"
                f"User ID: {teacher_id}\n"
                f"Role: O'qituvchi"
            )
        else:
            # Create new user as teacher
            new_teacher = User(
                telegram_id=teacher_id,
                username=target_user.username,
                full_name=target_user.full_name,
                role=UserRole.TEACHER,
                is_registered=True,
            )
            session.add(new_teacher)
            await session.commit()
            name = target_user.full_name or target_user.username or f"ID: {teacher_id}"
            await message.answer(
                f"✅ Yangi o'qituvchi yaratildi!\n\n"
                f"Foydalanuvchi: <b>{name}</b>\n"
                f"Username: @{target_user.username or 'yo\'q'}\n"
                f"User ID: {teacher_id}\n"
                f"Role: O'qituvchi"
            )


@dp.message(AdminStates.waiting_teacher_username)
async def handle_teacher_identifier(message: Message, state: FSMContext) -> None:
    identifier = message.text.strip() if message.text else ""
    
    if not identifier:
        await message.answer("Iltimos, username yoki user ID kiriting.")
        return
    
    teacher_id: int | None = None
    
    # Check if it's a username (starts with @)
    if identifier.startswith("@"):
        username = identifier[1:]  # Remove @
        async for session in get_session():
            stmt = select(User).where(User.username == username)
            teacher_user = await session.scalar(stmt)
            if teacher_user:
                teacher_id = teacher_user.telegram_id
            else:
                await message.answer(
                    f"Foydalanuvchi '{identifier}' topilmadi.\n"
                    "Iltimos, botga /start yuborishi kerak."
                )
                await state.clear()
                return
    else:
        # Try to parse as user ID
        try:
            teacher_id = int(identifier)
        except ValueError:
            await message.answer(
                "Noto'g'ri format. Username (@username) yoki user ID (raqam) kiriting."
            )
            return
    
    if not teacher_id:
        await message.answer("Xatolik: foydalanuvchi topilmadi.")
        await state.clear()
        return
    
    # Update or create user as teacher
    async for session in get_session():
        stmt = select(User).where(User.telegram_id == teacher_id)
        teacher_user = await session.scalar(stmt)
        
        if teacher_user:
            teacher_user.role = UserRole.TEACHER
            teacher_user.is_registered = True  # Teachers are auto-registered
            await session.commit()
            await message.answer(
                f"✅ O'qituvchi muvaffaqiyatli qo'shildi!\n\n"
                f"Foydalanuvchi: {teacher_user.full_name or teacher_user.username or f'ID: {teacher_id}'}\n"
                f"Role: O'qituvchi"
            )
        else:
            # Create new user as teacher
            new_teacher = User(
                telegram_id=teacher_id,
                role=UserRole.TEACHER,
                is_registered=True,
            )
            session.add(new_teacher)
            await session.commit()
            await message.answer(
                f"✅ Yangi o'qituvchi yaratildi!\n\n"
                f"User ID: {teacher_id}\n"
                f"Role: O'qituvchi\n\n"
                f"Foydalanuvchi botga /start yuborishi kerak."
            )
    
    await state.clear()


async def main() -> None:
    await init_db()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())


