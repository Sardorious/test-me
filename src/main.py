import asyncio
from datetime import datetime, timezone
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
    FSInputFile,
)

from sqlalchemy import and_, func, select

from .bot_states import TestStates, RegistrationStates, AdminStates, UploadWordsStates, DeleteWordsStates, DeleteUnitStates, DeleteDegreeStates
from .config import settings
from .db import get_session, init_db
from .models import (
    TestDirection,
    TestQuestion,
    TestSession,
    TestStatus,
    Unit,
    User,
    Word,
    WordList,
)


bot = Bot(
    token=settings.bot_token,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()


CEFR_LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"]


def normalize_answer(text: str) -> str:
    """
    Normalize answer text for case-insensitive comparison.
    Converts to lowercase, strips whitespace, and handles special cases.
    """
    if not text:
        return ""
    # Convert to lowercase and strip whitespace
    normalized = text.lower().strip()
    # Remove extra whitespace (multiple spaces)
    normalized = " ".join(normalized.split())
    return normalized


def compare_answers(student_answer: str, correct_answer: str) -> bool:
    """
    Compare student answer with correct answer(s) in a case-insensitive manner.
    Supports multiple correct answers separated by semicolon (;).
    Both answers are normalized (lowercased, trimmed) before comparison.
    Case (big/small letters) does not affect the result.
    """
    if not student_answer:
        return False
    
    # Normalize student answer
    student_normalized = normalize_answer(student_answer)
    
    # Split correct answers by semicolon and check each one
    correct_answers = [normalize_answer(ans.strip()) for ans in correct_answer.split(";")]
    
    # Check if student answer matches any of the correct answers
    return student_normalized in correct_answers


def has_teacher_or_admin_permission(user: User) -> bool:
    """Check if user has teacher or admin permissions (admins have all teacher permissions)."""
    return user.is_teacher or user.is_admin


def has_admin_permission(user: User) -> bool:
    """Check if user has admin permission."""
    return user.is_admin


def has_student_permission(user: User) -> bool:
    """Check if user has student permission."""
    return user.is_student


async def get_or_create_user(tg_user, role_hint=None) -> User:
    async for session in get_session():
        stmt = select(User).where(User.telegram_id == tg_user.id)
        user = await session.scalar(stmt)
        
        # Check if user is in ADMIN_IDS (should be Teacher)
        should_be_teacher = tg_user.id in settings.admin_ids
        
        if user:
            # Update existing user if they're in ADMIN_IDS but not marked as teacher
            if should_be_teacher and not user.is_teacher:
                user.is_teacher = True
                user.is_student = True  # Ensure they're also a student
                user.is_registered = True  # Teachers are auto-registered
                await session.commit()
                await session.refresh(user)
            # Update username and full_name if changed
            if tg_user.username != user.username or tg_user.full_name != user.full_name:
                user.username = tg_user.username
                user.full_name = tg_user.full_name
                await session.commit()
            return user  # type: ignore[return-value]

        # Set roles: every new user is a student
        # If chat ID is in ADMIN_IDS, they also become a teacher
        is_admin = False  # No longer using admin_ids for admin role
        is_teacher = should_be_teacher  # ADMIN_IDS now means Teacher
        is_student = True  # All users are students by default
        
        # Note: role_hint is deprecated but kept for backward compatibility
        # New code should set is_admin, is_teacher, is_student directly

        user = User(
            telegram_id=tg_user.id,
            username=tg_user.username,
            full_name=tg_user.full_name,
            is_admin=is_admin,
            is_teacher=is_teacher,
            is_student=is_student,
            is_registered=is_teacher,  # Teachers are auto-registered
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
    
    # Check if user is blocked
    if user.is_blocked:
        await message.answer("❌ Sizning akkauntingiz bloklangan. Admin bilan bog'laning.")
        return
    
    # Check if student needs registration
    if user.is_student and not user.is_registered:
        await state.set_state(RegistrationStates.waiting_first_name)
        await message.answer(
            "Salom! Ro'yxatdan o'tish uchun quyidagi ma'lumotlarni kiriting.\n\n"
            "Ismingizni kiriting:"
        )
        return
    
    # Build menu based on user roles
    roles = []
    if user.is_admin:
        roles.append("Admin")
    if user.is_teacher:
        roles.append("O'qituvchi")
    if user.is_student:
        roles.append("O'quvchi")
    
    role_text = ", ".join(roles) if roles else "Foydalanuvchi"
    
    if user.is_admin:
        text = (
            f"Salom, {role_text}! Bot boshqaruv buyruqlari:\n\n"
            "<b>O'qituvchi buyruqlari:</b>\n"
            "/view_results - O'quvchilar natijalarini ko'rish\n"
            "/upload_words - So'zlar yuklash\n"
            "/delete_words - So'zlar ro'yxatini o'chirish\n"
            "/delete_unit - Unitni o'chirish\n\n"
            "<b>Admin buyruqlari:</b>\n"
            "/add_teacher - O'qituvchi qo'shish\n"
            "/manage_users - Foydalanuvchilarni boshqarish\n"
            "/delete_degree - Degree (CEFR daraja)ni o'chirish"
        )
        if user.is_student:
            text += "\n\n<b>O'quvchi buyruqlari:</b>\n/start_test - Testni boshlash"
    elif user.is_teacher:
        text = (
            f"Salom, {role_text}! Bot buyruqlari:\n"
            "/view_results - O'quvchilar natijalarini ko'rish\n"
            "/upload_words - So'zlar yuklash\n"
            "/delete_words - So'zlar ro'yxatini o'chirish\n"
            "/delete_unit - Unitni o'chirish"
        )
        if user.is_student:
            text += "\n\n<b>O'quvchi buyruqlari:</b>\n/start_test - Testni boshlash"
    else:
        text = (
            "Salom! Men turkcha–o'zbekcha so'zlarni o'rganish uchun botman.\n\n"
            "Testni boshlash: /start_test"
        )
    await message.answer(text)


# ========== REGISTRATION HANDLERS ==========

@dp.message(Command("register"))
async def cmd_register(message: Message, state: FSMContext) -> None:
    """Allow students to start registration."""
    user = await get_or_create_user(message.from_user)
    
    # Check if user is blocked
    if user.is_blocked:
        await message.answer("❌ Sizning akkauntingiz bloklangan. Admin bilan bog'laning.")
        return
    
    # Check if already registered
    if user.is_registered:
        await message.answer("Siz allaqachon ro'yxatdan o'tgansiz!")
        return
    
    # Check if admin/teacher (they don't need registration)
    if user.is_admin or user.is_teacher:
        await message.answer("Siz admin yoki o'qituvchisiz. Ro'yxatdan o'tish shart emas.")
        return
    
    await state.set_state(RegistrationStates.waiting_first_name)
    await message.answer(
        "Ro'yxatdan o'tish.\n\n"
        "Ismingizni kiriting:"
    )


@dp.message(RegistrationStates.waiting_first_name)
async def handle_first_name(message: Message, state: FSMContext) -> None:
    user = await get_or_create_user(message.from_user)
    
    # Check if user is blocked
    if user.is_blocked:
        await message.answer("❌ Sizning akkauntingiz bloklangan. Admin bilan bog'laning.")
        await state.clear()
        return
    
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
    async for session in get_session():
        # Get user in this session
        stmt = select(User).where(User.telegram_id == callback.from_user.id)
        user = await session.scalar(stmt)
        
        if not user:
            # Create user if doesn't exist
            user = User(
                telegram_id=callback.from_user.id,
                username=callback.from_user.username,
                full_name=callback.from_user.full_name,
                is_admin=False,
                is_teacher=callback.from_user.id in settings.admin_ids,
                is_student=True,
                is_registered=True,
            )
            session.add(user)
        
        # Update registration data
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
    if user.is_student and not user.is_registered:
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
        # Select all words for this level (through Unit)
        stmt = (
            select(Word)
            .join(WordList)
            .join(Unit)
            .where(Unit.cefr_level == level)
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
                # uzbek field may contain multiple translations separated by semicolon
                correct_answer = w.uzbek
            else:
                shown_lang = "uz"
                # For UZ->TR, turkish is single, but we keep the format consistent
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
    user = await get_or_create_user(message.from_user)
    
    # Check if user is blocked
    if user.is_blocked:
        await message.answer("❌ Sizning akkauntingiz bloklangan. Admin bilan bog'laning.")
        await state.clear()
        return
    
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
        q.is_correct = compare_answers(answer_text, q.correct_answer)
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
        test_session.finished_at = datetime.now(timezone.utc)
        await session.commit()

        await state.clear()

        # Get incorrect answers for student
        incorrect_questions = [q for q in questions if not q.is_correct and q.student_answer]
        incorrect_count = len(incorrect_questions)

        text = (
            f"Test yakunlandi!\n\n"
            f"Umumiy savollar: <b>{total}</b>\n"
            f"To'g'ri javoblar: <b>{correct}</b>\n"
            f"Javobsiz (yo'q / bo'sh): <b>{no_answer}</b>\n"
            f"Natija: <b>{percent}%</b>"
        )
        await message.answer(text)
        
        # Show mistakes to student if there are any
        if incorrect_count > 0:
            await _show_mistakes_to_student(message, test_session_id, incorrect_questions)


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
    
    if not has_teacher_or_admin_permission(user):
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
    
    if not has_teacher_or_admin_permission(user):
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
                today = datetime.now(timezone.utc).date()
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
            
            query = query.order_by(TestSession.finished_at.desc())
            
            results = await session.execute(query)
            rows = results.all()
            
            if not rows:
                await callback.message.edit_text(
                    "Natijalar topilmadi.",
                    reply_markup=None
                )
                await callback.answer()
                return
            
            # Group results by user
            from collections import defaultdict
            user_sessions = defaultdict(list)
            for test_session, student in rows:
                user_sessions[student.id].append((test_session, student))
            
            # Format results - grouped by user
            text_parts = ["📊 <b>O'quvchilar natijalari:</b>\n"]
            
            for student_id, sessions_list in user_sessions.items():
                # Sort by finished_at descending (most recent first)
                # Handle None finished_at by using a very old date
                min_date = datetime(1970, 1, 1, tzinfo=timezone.utc)
                sessions_list.sort(key=lambda x: x[0].finished_at or min_date, reverse=True)
                
                # Get student info from first session
                student = sessions_list[0][1]
                student_name = f"{student.first_name or ''} {student.last_name or ''}".strip()
                if not student_name:
                    student_name = student.full_name or f"ID: {student.telegram_id}"
                
                # Show last test in detail
                last_session, _ = sessions_list[0]
                
                # Calculate stats for last test
                questions_query = (
                    select(TestQuestion)
                    .where(TestQuestion.test_session_id == last_session.id)
                )
                questions_result = await session.execute(questions_query)
                questions = questions_result.scalars().all()
                
                total = len(questions)
                correct = sum(1 for q in questions if q.is_correct)
                percent = int((correct / total) * 100) if total else 0
                
                direction_text = "TR➜UZ" if last_session.direction == TestDirection.TR_TO_UZ else "UZ➜TR"
                finished_date = last_session.finished_at.strftime("%Y-%m-%d %H:%M") if last_session.finished_at else "N/A"
                incorrect_count = total - correct
                
                text_parts.append(
                    f"\n👤 <b>{student_name}</b>\n"
                    f"📅 {finished_date}\n"
                    f"🎓 {last_session.cefr_level} | {direction_text}\n"
                    f"✅ {correct}/{total} ({percent}%)\n"
                    f"❌ Xatolar: {incorrect_count}"
                )
                
                # Add button to view mistakes if there are any
                if incorrect_count > 0:
                    text_parts[-1] += f"\n🔍 Xatolarni ko'rish: /view_mistakes_{last_session.id}"
                
                # Show other 5 tests as clickable links (if more than 1 test)
                if len(sessions_list) > 1:
                    other_tests = sessions_list[1:6]  # Next 5 tests
                    test_links = [f"/view_mistakes_{test_sess.id}" for test_sess, _ in other_tests]
                    
                    if test_links:
                        text_parts.append(f"\n📋 Boshqa testlar: {', '.join(test_links)}")
                
                text_parts.append(f"{'─' * 20}")
            
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


# ========== VIEW MISTAKES HANDLERS ==========

@dp.message(F.text.startswith("/view_mistakes_"))
async def cmd_view_mistakes(message: Message, state: FSMContext) -> None:
    """View mistakes for a specific test session."""
    user = await get_or_create_user(message.from_user)
    
    if not has_teacher_or_admin_permission(user):
        await message.answer("Bu buyruq faqat o'qituvchilar va adminlar uchun.")
        return
    
    # Parse command: /view_mistakes_123
    text = message.text or ""
    if not text.startswith("/view_mistakes_"):
        await message.answer(
            "Noto'g'ri format. Quyidagicha ishlating:\n"
            "/view_results - natijalarni ko'ring va xatolarni ko'rish tugmasini bosing"
        )
        return
    
    try:
        # Extract session ID from /view_mistakes_123
        session_id_str = text.replace("/view_mistakes_", "").strip()
        session_id = int(session_id_str)
    except ValueError:
        await message.answer("Noto'g'ri test ID.")
        return
    
    await _show_mistakes(message, session_id)


async def _show_mistakes_to_student(
    message: Message, session_id: int, incorrect_questions: list
) -> None:
    """Show incorrect answers to student at the end of test."""
    async for session in get_session():
        test_session = await session.get(TestSession, session_id)
        if not test_session:
            return
        
        # Get words for display
        word_ids = [q.word_id for q in incorrect_questions]
        words_stmt = select(Word).where(Word.id.in_(word_ids))
        words_result = await session.scalars(words_stmt)
        words_dict = {w.id: w for w in words_result.all()}
        
        direction_text = "TR➜UZ" if test_session.direction == TestDirection.TR_TO_UZ else "UZ➜TR"
        
        text_parts = [
            f"❌ <b>Xatolaringiz:</b>\n",
            f"🎓 {test_session.cefr_level} | {direction_text}\n",
            f"Xatolar soni: <b>{len(incorrect_questions)}</b>\n",
            f"{'=' * 25}\n"
        ]
        
        for q in incorrect_questions:
            word = words_dict.get(q.word_id)
            if not word:
                continue
            
            # Show the question word
            if q.shown_lang == "tr":
                question_word = word.turkish
                answer_lang = "Uzbek"
            else:
                question_word = word.uzbek
                answer_lang = "Turkish"
            
            student_answer = q.student_answer or "(javob yo'q)"
            correct_answer = q.correct_answer
            # Format multiple correct answers nicely
            correct_answers_list = [ans.strip() for ans in correct_answer.split(";")]
            if len(correct_answers_list) > 1:
                correct_answer_display = " / ".join([f"<code>{ans}</code>" for ans in correct_answers_list])
            else:
                correct_answer_display = f"<code>{correct_answer}</code>"
            
            text_parts.append(
                f"\n❓ <b>{question_word}</b> ({answer_lang})\n"
                f"❌ Sizning javobingiz: <code>{student_answer}</code>\n"
                f"✅ To'g'ri javob(lar): {correct_answer_display}\n"
                f"{'─' * 20}"
            )
        
        # Send in chunks if too long
        full_text = "\n".join(text_parts)
        if len(full_text) > 4000:
            # Send header first
            await message.answer(text_parts[0] + text_parts[1] + text_parts[2] + text_parts[3])
            
            # Send mistakes in chunks
            chunk = ""
            for part in text_parts[4:]:
                if len(chunk + part) > 4000:
                    await message.answer(chunk)
                    chunk = part
                else:
                    chunk += part
            if chunk:
                await message.answer(chunk)
        else:
            await message.answer(full_text)


async def _show_mistakes(message: Message, session_id: int) -> None:
    """Show incorrect answers for a test session with ability to mark as correct."""
    async for session in get_session():
        # Get test session
        test_session = await session.get(TestSession, session_id)
        if not test_session:
            await message.answer("Test topilmadi.")
            return
        
        # Get student
        student = await session.get(User, test_session.student_id)
        if not student:
            await message.answer("O'quvchi topilmadi.")
            return
        
        # Get all questions
        questions_stmt = select(TestQuestion).where(
            TestQuestion.test_session_id == session_id
        ).order_by(TestQuestion.position)
        questions_result = await session.scalars(questions_stmt)
        questions = list(questions_result.all())
        
        # Filter incorrect answers
        incorrect_questions = [q for q in questions if not q.is_correct and q.student_answer]
        
        if not incorrect_questions:
            await message.answer(
                f"✅ <b>{student.first_name or ''} {student.last_name or ''}</b> uchun xatolar topilmadi.\n"
                f"Barcha javoblar to'g'ri!"
            )
            return
        
        # Get words for display
        word_ids = [q.word_id for q in incorrect_questions]
        words_stmt = select(Word).where(Word.id.in_(word_ids))
        words_result = await session.scalars(words_stmt)
        words_dict = {w.id: w for w in words_result.all()}
        
        # Format mistakes with inline buttons
        student_name = f"{student.first_name or ''} {student.last_name or ''}".strip()
        if not student_name:
            student_name = student.full_name or f"ID: {student.telegram_id}"
        
        direction_text = "TR➜UZ" if test_session.direction == TestDirection.TR_TO_UZ else "UZ➜TR"
        
        # Send mistakes one by one with buttons (Telegram limit for inline keyboards)
        header_text = (
            f"❌ <b>{student_name} - Xatolar</b>\n"
            f"📅 {test_session.finished_at.strftime('%Y-%m-%d %H:%M') if test_session.finished_at else 'N/A'}\n"
            f"🎓 {test_session.cefr_level} | {direction_text}\n"
            f"Xatolar soni: <b>{len(incorrect_questions)}</b>\n"
            f"{'=' * 25}\n"
            f"\nO'qituvchi: Agar javob sinonim yoki to'g'ri bo'lsa, 'To'g'ri deb belgilash' tugmasini bosing."
        )
        await message.answer(header_text)
        
        # Send each mistake with a button to mark as correct
        for q in incorrect_questions:
            word = words_dict.get(q.word_id)
            if not word:
                continue
            
            # Show the question word
            if q.shown_lang == "tr":
                question_word = word.turkish
                answer_lang = "Uzbek"
            else:
                question_word = word.uzbek
                answer_lang = "Turkish"
            
            student_answer = q.student_answer or "(javob yo'q)"
            correct_answer = q.correct_answer
            # Format multiple correct answers nicely
            correct_answers_list = [ans.strip() for ans in correct_answer.split(";")]
            if len(correct_answers_list) > 1:
                correct_answer_display = " / ".join([f"<code>{ans}</code>" for ans in correct_answers_list])
            else:
                correct_answer_display = f"<code>{correct_answer}</code>"
            
            mistake_text = (
                f"\n❓ <b>{question_word}</b> ({answer_lang})\n"
                f"❌ O'quvchi javobi: <code>{student_answer}</code>\n"
                f"✅ Kutilgan javob(lar): {correct_answer_display}\n"
                f"{'─' * 20}"
            )
            
            # Add inline button to mark as correct
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[[
                    InlineKeyboardButton(
                        text="✅ To'g'ri deb belgilash",
                        callback_data=f"mark_correct:{q.id}"
                    )
                ]]
            )
            
            await message.answer(mistake_text, reply_markup=keyboard)


@dp.callback_query(F.data.startswith("mark_correct:"))
async def handle_mark_correct(callback: CallbackQuery) -> None:
    """Mark a student answer as correct (for synonyms or alternative correct answers)."""
    user = await get_or_create_user(callback.from_user)
    
    if not has_teacher_or_admin_permission(user):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    
    # Parse question ID
    try:
        question_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer("Xatolik: noto'g'ri format.", show_alert=True)
        return
    
    async for session in get_session():
        # Get question
        question = await session.get(TestQuestion, question_id)
        if not question:
            await callback.answer("Savol topilmadi.", show_alert=True)
            return
        
        # Check if already correct
        if question.is_correct:
            await callback.answer("Bu javob allaqachon to'g'ri deb belgilangan.", show_alert=True)
            return
        
        # Mark as correct
        question.is_correct = True
        await session.commit()
        
        # Get test session to update stats
        test_session = await session.get(TestSession, question.test_session_id)
        if test_session:
            # Recalculate stats (optional - for consistency)
            questions_stmt = select(TestQuestion).where(
                TestQuestion.test_session_id == test_session.id
            )
            all_questions = await session.scalars(questions_stmt)
            correct_count = sum(1 for q in all_questions.all() if q.is_correct)
            # Note: We don't update test_session here, but the stats will be recalculated when viewing results
        
        # Get word for display
        word = await session.get(Word, question.word_id)
        if word:
            if question.shown_lang == "tr":
                question_word = word.turkish
            else:
                question_word = word.uzbek
            
            await callback.message.edit_text(
                f"✅ <b>Javob to'g'ri deb belgilandi!</b>\n\n"
                f"❓ {question_word}\n"
                f"O'quvchi javobi: <code>{question.student_answer}</code>\n"
                f"Kutilgan javob: <code>{question.correct_answer}</code>\n\n"
                f"Bu javob endi to'g'ri deb hisoblanadi."
            )
        else:
            await callback.message.edit_text(
                f"✅ <b>Javob to'g'ri deb belgilandi!</b>\n\n"
                f"O'quvchi javobi: <code>{question.student_answer}</code>\n"
                f"Bu javob endi to'g'ri deb hisoblanadi."
            )
        
        await callback.answer("✅ Javob to'g'ri deb belgilandi!")


# ========== ADMIN COMMANDS ==========

@dp.message(Command("add_teacher"))
async def cmd_add_teacher(message: Message, state: FSMContext) -> None:
    user = await get_or_create_user(message.from_user)
    
    if not has_admin_permission(user):
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
            teacher_user.is_teacher = True  # Add teacher role (keep existing roles)
            teacher_user.is_registered = True
            await session.commit()
            roles = []
            if teacher_user.is_admin:
                roles.append("Admin")
            if teacher_user.is_teacher:
                roles.append("O'qituvchi")
            if teacher_user.is_student:
                roles.append("O'quvchi")
            role_text = ", ".join(roles) if roles else "Foydalanuvchi"
            
            name = teacher_user.full_name or teacher_user.username or f"ID: {teacher_id}"
            await message.answer(
                f"✅ O'qituvchi muvaffaqiyatli qo'shildi!\n\n"
                f"Foydalanuvchi: <b>{name}</b>\n"
                f"Username: @{target_user.username or 'yo\'q'}\n"
                f"User ID: {teacher_id}\n"
                f"Rollar: {role_text}"
            )
        else:
            # Create new user as teacher (also student by default)
            new_teacher = User(
                telegram_id=teacher_id,
                username=target_user.username,
                full_name=target_user.full_name,
                is_admin=False,
                is_teacher=True,
                is_student=True,  # Default to student
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
                f"Rollar: O'qituvchi, O'quvchi"
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
            teacher_user.is_teacher = True  # Add teacher role (keep existing roles)
            teacher_user.is_registered = True  # Teachers are auto-registered
            await session.commit()
            roles = []
            if teacher_user.is_admin:
                roles.append("Admin")
            if teacher_user.is_teacher:
                roles.append("O'qituvchi")
            if teacher_user.is_student:
                roles.append("O'quvchi")
            role_text = ", ".join(roles) if roles else "Foydalanuvchi"
            
            await message.answer(
                f"✅ O'qituvchi muvaffaqiyatli qo'shildi!\n\n"
                f"Foydalanuvchi: {teacher_user.full_name or teacher_user.username or f'ID: {teacher_id}'}\n"
                f"Rollar: {role_text}"
            )
        else:
            # Create new user as teacher (also student by default)
            new_teacher = User(
                telegram_id=teacher_id,
                is_admin=False,
                is_teacher=True,
                is_student=True,  # Default to student
                is_registered=True,
            )
            session.add(new_teacher)
            await session.commit()
            await message.answer(
                f"✅ Yangi o'qituvchi yaratildi!\n\n"
                f"User ID: {teacher_id}\n"
                f"Rollar: O'qituvchi, O'quvchi\n\n"
                f"Foydalanuvchi botga /start yuborishi kerak."
            )
    
    await state.clear()


# ========== USER MANAGEMENT HANDLERS ==========

@dp.message(Command("manage_users"))
async def cmd_manage_users(message: Message, state: FSMContext) -> None:
    user = await get_or_create_user(message.from_user)
    
    if not has_admin_permission(user):
        await message.answer("Bu buyruq faqat adminlar uchun.")
        return
    
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="👤 Foydalanuvchini o'chirish", callback_data="user_action:remove"),
                InlineKeyboardButton(text="🚫 Bloklash", callback_data="user_action:block"),
            ],
            [
                InlineKeyboardButton(text="✅ Blokdan chiqarish", callback_data="user_action:unblock"),
                InlineKeyboardButton(text="📋 Ro'yxatni ko'rish", callback_data="user_action:list"),
            ],
        ]
    )
    
    await message.answer(
        "👥 <b>Foydalanuvchilarni boshqarish</b>\n\n"
        "Amalni tanlang:",
        reply_markup=keyboard
    )


@dp.callback_query(F.data.startswith("user_action:"))
async def handle_user_action(callback: CallbackQuery, state: FSMContext) -> None:
    user = await get_or_create_user(callback.from_user)
    
    if not has_admin_permission(user):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    
    action = callback.data.split(":", 1)[1]
    
    if action == "list":
        await _list_users(callback.message)
        await callback.answer()
        return
    
    await state.update_data(user_action=action)
    await state.set_state(AdminStates.waiting_user_identifier)
    
    action_texts = {
        "remove": "o'chirish",
        "block": "bloklash",
        "unblock": "blokdan chiqarish"
    }
    
    await callback.message.edit_text(
        f"Foydalanuvchini {action_texts.get(action, action)}.\n\n"
        "Quyidagi usullardan birini tanlang:\n"
        "• Foydalanuvchining xabariga javob bering\n"
        "• Foydalanuvchining xabarini forward qiling\n"
        "• Username (@username) yoki user ID (123456789) yuboring"
    )
    await callback.answer()


@dp.message(AdminStates.waiting_user_identifier)
async def handle_user_identifier_for_action(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    action = data.get("user_action")
    
    if not action:
        await message.answer("Xatolik: amal topilmadi.")
        await state.clear()
        return
    
    target_user = None
    
    # Check if replying to a message
    if message.reply_to_message and message.reply_to_message.from_user:
        target_user = message.reply_to_message.from_user
    # Check if forwarding a message
    elif message.forward_from:
        target_user = message.forward_from
    # Check if text input (username or ID)
    elif message.text:
        identifier = message.text.strip()
        if identifier.startswith("@"):
            username = identifier[1:]
            async for session in get_session():
                stmt = select(User).where(User.username == username)
                db_user = await session.scalar(stmt)
                if db_user:
                    # We need to get telegram_id, but we can't get User object from telegram
                    # So we'll work with the database user
                    await _perform_user_action(message, action, db_user.id, state)
                    return
            await message.answer(f"Foydalanuvchi '{identifier}' topilmadi.")
            await state.clear()
            return
        else:
            try:
                user_id = int(identifier)
                async for session in get_session():
                    stmt = select(User).where(User.telegram_id == user_id)
                    db_user = await session.scalar(stmt)
                    if db_user:
                        await _perform_user_action(message, action, db_user.id, state)
                        return
                await message.answer(f"Foydalanuvchi ID {user_id} topilmadi.")
                await state.clear()
                return
            except ValueError:
                await message.answer("Noto'g'ri format. Username (@username) yoki user ID kiriting.")
                return
    
    if target_user:
        async for session in get_session():
            stmt = select(User).where(User.telegram_id == target_user.id)
            db_user = await session.scalar(stmt)
            if db_user:
                await _perform_user_action(message, action, db_user.id, state)
            else:
                await message.answer("Foydalanuvchi bazada topilmadi.")
                await state.clear()
    else:
        await message.answer("Iltimos, foydalanuvchi xabariga javob bering, forward qiling yoki username/ID kiriting.")


async def _perform_user_action(message: Message, action: str, user_db_id: int, state: FSMContext) -> None:
    """Perform user action (remove, block, unblock)."""
    async for session in get_session():
        target_user = await session.get(User, user_db_id)
        
        if not target_user:
            await message.answer("Foydalanuvchi topilmadi.")
            await state.clear()
            return
        
        # Prevent admin from modifying themselves
        admin_user = await get_or_create_user(message.from_user)
        if target_user.id == admin_user.id:
            await message.answer("❌ O'zingizni o'zgartira olmaysiz.")
            await state.clear()
            return
        
        # Prevent modifying other admins
        if target_user.is_admin:
            await message.answer("❌ Boshqa adminlarni o'zgartira olmaysiz.")
            await state.clear()
            return
        
        if action == "remove":
            # Delete user (cascade will delete test sessions)
            user_name = f"{target_user.first_name or ''} {target_user.last_name or ''}".strip()
            if not user_name:
                user_name = target_user.full_name or f"ID: {target_user.telegram_id}"
            
            await session.delete(target_user)
            await session.commit()
            
            await message.answer(
                f"✅ Foydalanuvchi o'chirildi!\n\n"
                f"Foydalanuvchi: <b>{user_name}</b>\n"
                f"Telegram ID: {target_user.telegram_id}"
            )
        
        elif action == "block":
            target_user.is_blocked = True
            await session.commit()
            
            user_name = f"{target_user.first_name or ''} {target_user.last_name or ''}".strip()
            if not user_name:
                user_name = target_user.full_name or f"ID: {target_user.telegram_id}"
            
            await message.answer(
                f"🚫 Foydalanuvchi bloklandi!\n\n"
                f"Foydalanuvchi: <b>{user_name}</b>\n"
                f"Telegram ID: {target_user.telegram_id}"
            )
        
        elif action == "unblock":
            target_user.is_blocked = False
            await session.commit()
            
            user_name = f"{target_user.first_name or ''} {target_user.last_name or ''}".strip()
            if not user_name:
                user_name = target_user.full_name or f"ID: {target_user.telegram_id}"
            
            await message.answer(
                f"✅ Foydalanuvchi blokdan chiqarildi!\n\n"
                f"Foydalanuvchi: <b>{user_name}</b>\n"
                f"Telegram ID: {target_user.telegram_id}"
            )
    
    await state.clear()


async def _list_users(message: Message) -> None:
    """List all users with their status."""
    async for session in get_session():
        stmt = select(User).order_by(User.created_at.desc()).limit(50)
        users_result = await session.scalars(stmt)
        users = list(users_result.all())
        
        if not users:
            await message.answer("Hech qanday foydalanuvchi topilmadi.")
            return
        
        text_parts = ["👥 <b>Foydalanuvchilar ro'yxati:</b>\n"]
        
        for u in users:
            # Build role display
            roles = []
            role_emojis = []
            if u.is_admin:
                roles.append("Admin")
                role_emojis.append("👑")
            if u.is_teacher:
                roles.append("O'qituvchi")
                role_emojis.append("👨‍🏫")
            if u.is_student:
                roles.append("O'quvchi")
                role_emojis.append("👤")
            
            role_text = ", ".join(roles) if roles else "Foydalanuvchi"
            role_emoji = "".join(role_emojis) if role_emojis else "👤"
            
            status = "🚫 Bloklangan" if u.is_blocked else "✅ Faol"
            registered = "✅" if u.is_registered else "❌"
            
            name = f"{u.first_name or ''} {u.last_name or ''}".strip()
            if not name:
                name = u.full_name or f"ID: {u.telegram_id}"
            
            text_parts.append(
                f"\n{role_emoji} <b>{name}</b>\n"
                f"Rollar: {role_text} | {status}\n"
                f"Ro'yxatdan o'tgan: {registered}\n"
                f"ID: {u.telegram_id}\n"
                f"{'─' * 20}"
            )
        
        full_text = "\n".join(text_parts)
        if len(full_text) > 4000:
            # Send in chunks
            chunk = ""
            for part in text_parts:
                if len(chunk + part) > 4000:
                    await message.answer(chunk)
                    chunk = part
                else:
                    chunk += part
            if chunk:
                await message.answer(chunk)
        else:
            await message.answer(full_text)


# ========== UPLOAD WORDS HANDLERS ==========

@dp.message(Command("upload_words"))
async def cmd_upload_words(message: Message, state: FSMContext) -> None:
    user = await get_or_create_user(message.from_user)
    
    if not has_teacher_or_admin_permission(user):
        await message.answer("Bu buyruq faqat o'qituvchilar va adminlar uchun.")
        return
    
    await state.set_state(UploadWordsStates.choosing_level)
    await message.answer(
        "So'zlar ro'yxatini yuklash.\n\n"
        "Qaysi CEFR darajasiga so'zlar qo'shamiz?",
        reply_markup=build_levels_keyboard()
    )


def build_units_keyboard(units: list[Unit], level: str) -> InlineKeyboardMarkup:
    """Build keyboard for selecting or creating units (1-20 per degree)."""
    buttons = []
    
    # Show existing units
    if units:
        for unit in sorted(units, key=lambda u: u.unit_number):
            button_text = f"Unit {unit.unit_number}: {unit.name}"
            buttons.append([
                InlineKeyboardButton(
                    text=button_text,
                    callback_data=f"unit:{unit.id}"
                )
            ])
    
    # Add button to create new unit (if less than 20 units exist)
    if len(units) < 20:
        buttons.append([
            InlineKeyboardButton(
                text=f"➕ Yangi Unit yaratish (Unit {len(units) + 1})",
                callback_data=f"unit:new"
            )
        ])
    
    buttons.append([
        InlineKeyboardButton(text="❌ Bekor qilish", callback_data="unit:cancel")
    ])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@dp.callback_query(UploadWordsStates.choosing_level, F.data.startswith("level:"))
async def upload_choose_level(callback: CallbackQuery, state: FSMContext) -> None:
    level = callback.data.split(":", 1)[1]
    await state.update_data(cefr_level=level)
    
    # Get existing units for this level
    async for session in get_session():
        stmt = select(Unit).where(Unit.cefr_level == level)
        units_result = await session.scalars(stmt)
        units = list(units_result.all())
    
    await state.set_state(UploadWordsStates.choosing_unit)
    await callback.message.edit_text(
        f"CEFR daraja: <b>{level}</b>\n\n"
        f"Mavjud Unitlar: {len(units)}/20\n\n"
        "Unitni tanlang yoki yangi Unit yarating:",
        reply_markup=build_units_keyboard(units, level)
    )
    await callback.answer()


@dp.callback_query(UploadWordsStates.choosing_unit, F.data.startswith("unit:"))
async def upload_choose_unit(callback: CallbackQuery, state: FSMContext) -> None:
    unit_data = callback.data.split(":", 1)[1]
    data = await state.get_data()
    level = data.get("cefr_level")
    
    if not level:
        await callback.answer("Xatolik: CEFR daraja topilmadi.", show_alert=True)
        await state.clear()
        return
    
    async for session in get_session():
        if unit_data == "new":
            # Create new unit
            # Find the next unit number
            stmt = select(Unit).where(Unit.cefr_level == level)
            existing_units = await session.scalars(stmt)
            existing_unit_numbers = {u.unit_number for u in existing_units.all()}
            
            # Find first available unit number (1-20)
            next_unit_number = None
            for i in range(1, 21):
                if i not in existing_unit_numbers:
                    next_unit_number = i
                    break
            
            if next_unit_number is None:
                await callback.answer("❌ Har bir Degree uchun maksimal 20 ta Unit bo'lishi mumkin!", show_alert=True)
                await state.clear()
                return
            
            # Create new unit
            new_unit = Unit(
                name=f"Unit {next_unit_number}",
                cefr_level=level,
                unit_number=next_unit_number,
            )
            session.add(new_unit)
            await session.commit()
            await session.refresh(new_unit)
            
            unit_id = new_unit.id
            unit_name = new_unit.name
        elif unit_data == "cancel":
            await callback.message.edit_text("❌ Bekor qilindi.")
            await callback.answer()
            await state.clear()
            return
        else:
            # Use existing unit
            try:
                unit_id = int(unit_data)
                unit = await session.get(Unit, unit_id)
                if not unit or unit.cefr_level != level:
                    await callback.answer("Xatolik: Unit topilmadi.", show_alert=True)
                    await state.clear()
                    return
                unit_name = unit.name
            except ValueError:
                await callback.answer("Xatolik: noto'g'ri Unit ID.", show_alert=True)
                await state.clear()
                return
        
        await state.update_data(unit_id=unit_id, unit_name=unit_name)
        await state.set_state(UploadWordsStates.waiting_file)
        await callback.message.edit_text(
            f"CEFR daraja: <b>{level}</b>\n"
            f"Unit: <b>{unit_name}</b>\n\n"
            "Endi .txt yoki .docx fayl yuboring.\n\n"
            "Format: har bir qatorda <code>turkish_word - uzbek_translation1; uzbek_translation2</code>\n"
            "Masalan: <code>merhaba - salom; assalomu alaykum</code>"
        )
        await callback.answer()


@dp.message(UploadWordsStates.waiting_file, F.document)
async def handle_upload_file(message: Message, state: FSMContext) -> None:
    document = message.document
    
    if not document:
        await message.answer("Fayl topilmadi. Iltimos, .txt yoki .docx fayl yuboring.")
        return
    
    file_name = document.file_name or ""
    
    # Check file extension
    if not (file_name.endswith(".txt") or file_name.endswith(".docx")):
        await message.answer("Faqat .txt yoki .docx fayllar qabul qilinadi.")
        return
    
    data = await state.get_data()
    cefr_level = data.get("cefr_level")
    unit_id = data.get("unit_id")
    
    if not cefr_level or not unit_id:
        await message.answer("Xatolik: CEFR daraja yoki Unit tanlanmagan.")
        await state.clear()
        return
    
    user = await get_or_create_user(message.from_user)
    
    # Download file
    await message.answer("Fayl yuklanmoqda va tahlil qilinmoqda...")
    
    try:
        file = await bot.get_file(document.file_id)
        file_path = file.file_path
        
        # Download file content
        import os
        import aiofiles
        
        temp_dir = "temp_uploads"
        os.makedirs(temp_dir, exist_ok=True)
        temp_file_path = os.path.join(temp_dir, file_name)
        
        await bot.download_file(file_path, temp_file_path)
        
        # Parse file
        words_parsed = []
        
        if file_name.endswith(".txt"):
            async with aiofiles.open(temp_file_path, "r", encoding="utf-8") as f:
                content = await f.read()
                lines = content.split("\n")
        else:  # .docx
            try:
                from docx import Document
                doc = Document(temp_file_path)
                lines = [para.text for para in doc.paragraphs if para.text.strip()]
            except ImportError:
                await message.answer(
                    "❌ .docx fayllarni qo'llab-quvvatlash uchun python-docx o'rnatilishi kerak:\n"
                    "pip install python-docx"
                )
                os.remove(temp_file_path)
                await state.clear()
                return
        
        # Parse lines
        valid_count = 0
        error_count = 0
        errors = []
        
        for line_num, line in enumerate(lines, 1):
            line = line.strip()
            if not line:
                continue
            
            # Parse format: turkish - uzbek1; uzbek2; uzbek3
            # Supports multiple translations separated by semicolon
            if " - " in line:
                parts = line.split(" - ", 1)
                if len(parts) == 2:
                    turkish = parts[0].strip()
                    uzbek_raw = parts[1].strip()
                    # Clean up multiple translations (remove extra spaces, normalize separators)
                    uzbek_translations = [t.strip() for t in uzbek_raw.split(";")]
                    uzbek_translations = [t for t in uzbek_translations if t]  # Remove empty strings
                    uzbek = "; ".join(uzbek_translations)  # Join with "; " for storage
                    
                    if turkish and uzbek:
                        words_parsed.append((turkish, uzbek))
                        valid_count += 1
                    else:
                        error_count += 1
                        errors.append(f"Qator {line_num}: bo'sh so'z")
                else:
                    error_count += 1
                    errors.append(f"Qator {line_num}: noto'g'ri format")
            else:
                error_count += 1
                errors.append(f"Qator {line_num}: '-' ajratuvchi topilmadi")
        
        # Clean up temp file
        os.remove(temp_file_path)
        
        if not words_parsed:
            await message.answer(
                "❌ Hech qanday to'g'ri so'z topilmadi.\n\n"
                "Format: <code>turkish_word - uzbek_translation</code>\n"
                "Masalan: <code>merhaba - salom</code>"
            )
            await state.clear()
            return
        
        # Save to database
        async for session in get_session():
            # Verify unit exists
            unit = await session.get(Unit, unit_id)
            if not unit:
                await message.answer("Xatolik: Unit topilmadi.")
                await state.clear()
                return
            
            # Create word list linked to unit
            word_list = WordList(
                name=f"{unit.name}_words_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
                unit_id=unit_id,
                owner_id=user.id,
            )
            session.add(word_list)
            await session.flush()
            
            # Add words
            words_to_add = []
            for turkish, uzbek in words_parsed:
                word = Word(
                    turkish=turkish,
                    uzbek=uzbek,
                    word_list_id=word_list.id,
                )
                words_to_add.append(word)
            
            session.add_all(words_to_add)
            await session.commit()
        
        # Success message
        unit_name = data.get("unit_name", "Unit")
        success_msg = (
            f"✅ So'zlar muvaffaqiyatli yuklandi!\n\n"
            f"CEFR daraja: <b>{cefr_level}</b>\n"
            f"Unit: <b>{unit_name}</b>\n"
            f"To'g'ri so'zlar: <b>{valid_count}</b>\n"
        )
        
        if error_count > 0:
            success_msg += f"Xatoliklar: <b>{error_count}</b>\n"
            if len(errors) <= 5:
                success_msg += "\nXatoliklar:\n" + "\n".join(errors[:5])
            else:
                success_msg += f"\nBirinchi 5 ta xatolik:\n" + "\n".join(errors[:5])
        
        await message.answer(success_msg)
        await state.clear()
        
    except Exception as e:
        await message.answer(f"❌ Xatolik yuz berdi: {str(e)}")
        await state.clear()


# ========== DELETE WORDS HANDLERS ==========

def build_wordlist_keyboard(wordlists: list[WordList]) -> InlineKeyboardMarkup:
    """Build keyboard for selecting word list to delete."""
    buttons = []
    for wl in wordlists:
        word_count = len(wl.words) if wl.words else 0
        button_text = f"{wl.name} ({word_count} so'z)"
        buttons.append([
            InlineKeyboardButton(
                text=button_text,
                callback_data=f"delete_wl:{wl.id}"
            )
        ])
    buttons.append([InlineKeyboardButton(text="❌ Bekor qilish", callback_data="delete_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@dp.message(Command("delete_words"))
async def cmd_delete_words(message: Message, state: FSMContext) -> None:
    user = await get_or_create_user(message.from_user)
    
    if not has_teacher_or_admin_permission(user):
        await message.answer("Bu buyruq faqat o'qituvchilar va adminlar uchun.")
        return
    
    await state.set_state(DeleteWordsStates.choosing_level)
    await message.answer(
        "So'zlar ro'yxatini o'chirish.\n\n"
        "Qaysi CEFR darajasidagi ro'yxatni o'chirmoqchisiz?",
        reply_markup=build_levels_keyboard()
    )


@dp.callback_query(DeleteWordsStates.choosing_level, F.data.startswith("level:"))
async def delete_choose_level(callback: CallbackQuery, state: FSMContext) -> None:
    level = callback.data.split(":", 1)[1]
    
    user = await get_or_create_user(callback.from_user)
    
    # Get word lists for this level (through Unit)
    async for session in get_session():
        # If user is teacher (not admin), only show their own word lists
        # If user is admin, show all word lists
        if user.is_teacher and not user.is_admin:
            stmt = (
                select(WordList)
                .join(Unit)
                .where(
                    Unit.cefr_level == level,
                    WordList.owner_id == user.id
                )
            )
        else:  # Admin can see all
            stmt = (
                select(WordList)
                .join(Unit)
                .where(Unit.cefr_level == level)
            )
        
        wordlists_result = await session.scalars(stmt)
        wordlists = list(wordlists_result.all())
        
        if not wordlists:
            await callback.message.edit_text(
                f"❌ {level} darajasida so'zlar ro'yxati topilmadi."
            )
            await callback.answer()
            await state.clear()
            return
        
        await state.update_data(cefr_level=level)
        await state.set_state(DeleteWordsStates.choosing_wordlist)
        
        text = f"CEFR daraja: <b>{level}</b>\n\nO'chirmoqchi bo'lgan ro'yxatni tanlang:"
        await callback.message.edit_text(text, reply_markup=build_wordlist_keyboard(wordlists))
        await callback.answer()


@dp.callback_query(DeleteWordsStates.choosing_wordlist, F.data.startswith("delete_wl:"))
async def delete_choose_wordlist(callback: CallbackQuery, state: FSMContext) -> None:
    wordlist_id = int(callback.data.split(":", 1)[1])
    
    user = await get_or_create_user(callback.from_user)
    
    async for session in get_session():
        stmt = select(WordList).where(WordList.id == wordlist_id)
        wordlist = await session.scalar(stmt)
        
        if not wordlist:
            await callback.answer("Ro'yxat topilmadi.", show_alert=True)
            await state.clear()
            return
        
        # Check permissions: teachers can only delete their own, admins can delete any
        if user.is_teacher and not user.is_admin and wordlist.owner_id != user.id:
            await callback.answer("Siz faqat o'z ro'yxatlaringizni o'chira olasiz.", show_alert=True)
            await state.clear()
            return
        
        # Get word count
        words_stmt = select(Word).where(Word.word_list_id == wordlist_id)
        words_result = await session.scalars(words_stmt)
        word_count = len(list(words_result.all()))
        
        await state.update_data(wordlist_id=wordlist_id)
        await state.set_state(DeleteWordsStates.confirming_delete)
        
        text = (
            f"⚠️ <b>Ro'yxatni o'chirish</b>\n\n"
            f"Nomi: <b>{wordlist.name}</b>\n"
            f"CEFR daraja: <b>{wordlist.cefr_level}</b>\n"
            f"So'zlar soni: <b>{word_count}</b>\n"
            f"Yaratilgan: {wordlist.created_at.strftime('%Y-%m-%d %H:%M')}\n\n"
            f"Bu ro'yxatni o'chirishni tasdiqlaysizmi?"
        )
        
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Ha, o'chirish", callback_data="delete_confirm"),
                    InlineKeyboardButton(text="❌ Yo'q", callback_data="delete_cancel"),
                ]
            ]
        )
        
        await callback.message.edit_text(text, reply_markup=keyboard)
        await callback.answer()


@dp.callback_query(DeleteWordsStates.confirming_delete, F.data == "delete_confirm")
async def delete_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    wordlist_id = data.get("wordlist_id")
    
    if not wordlist_id:
        await callback.answer("Xatolik: ro'yxat ID topilmadi.", show_alert=True)
        await state.clear()
        return
    
    user = await get_or_create_user(callback.from_user)
    
    async for session in get_session():
        stmt = select(WordList).where(WordList.id == wordlist_id)
        wordlist = await session.scalar(stmt)
        
        if not wordlist:
            await callback.answer("Ro'yxat topilmadi.", show_alert=True)
            await state.clear()
            return
        
        # Check permissions again: teachers can only delete their own, admins can delete any
        if user.is_teacher and not user.is_admin and wordlist.owner_id != user.id:
            await callback.answer("Ruxsat yo'q.", show_alert=True)
            await state.clear()
            return
        
        # Get word count before deletion
        words_stmt = select(Word).where(Word.word_list_id == wordlist_id)
        words_result = await session.scalars(words_stmt)
        word_count = len(list(words_result.all()))
        
        # Delete word list (cascade will delete words)
        await session.delete(wordlist)
        await session.commit()
        
        await callback.message.edit_text(
            f"✅ Ro'yxat muvaffaqiyatli o'chirildi!\n\n"
            f"Nomi: <b>{wordlist.name}</b>\n"
            f"O'chirilgan so'zlar: <b>{word_count}</b>"
        )
        await callback.answer("Ro'yxat o'chirildi.")
        await state.clear()


@dp.callback_query(DeleteWordsStates.confirming_delete, F.data == "delete_cancel")
async def delete_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text("❌ O'chirish bekor qilindi.")
    await callback.answer()
    await state.clear()


# ========== DELETE UNIT HANDLERS ==========

def build_units_for_deletion_keyboard(units: list[Unit]) -> InlineKeyboardMarkup:
    """Build keyboard for selecting unit to delete."""
    buttons = []
    
    for unit in sorted(units, key=lambda u: u.unit_number):
        # Count word lists in this unit
        word_list_count = len(unit.word_lists) if unit.word_lists else 0
        total_words = sum(len(wl.words) if wl.words else 0 for wl in unit.word_lists) if unit.word_lists else 0
        
        button_text = f"Unit {unit.unit_number}: {unit.name} ({word_list_count} ro'yxat, {total_words} so'z)"
        buttons.append([
            InlineKeyboardButton(
                text=button_text,
                callback_data=f"delete_unit:{unit.id}"
            )
        ])
    
    buttons.append([InlineKeyboardButton(text="❌ Bekor qilish", callback_data="unit_delete_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@dp.message(Command("delete_unit"))
async def cmd_delete_unit(message: Message, state: FSMContext) -> None:
    user = await get_or_create_user(message.from_user)
    
    if not has_teacher_or_admin_permission(user):
        await message.answer("Bu buyruq faqat o'qituvchilar va adminlar uchun.")
        return
    
    await state.set_state(DeleteUnitStates.choosing_level)
    await message.answer(
        "Unitni o'chirish.\n\n"
        "Qaysi CEFR darajasidagi Unitni o'chirmoqchisiz?",
        reply_markup=build_levels_keyboard()
    )


@dp.callback_query(DeleteUnitStates.choosing_level, F.data.startswith("level:"))
async def delete_unit_choose_level(callback: CallbackQuery, state: FSMContext) -> None:
    level = callback.data.split(":", 1)[1]
    
    user = await get_or_create_user(callback.from_user)
    
    # Get units for this level
    async for session in get_session():
        stmt = select(Unit).where(Unit.cefr_level == level)
        units_result = await session.scalars(stmt)
        units = list(units_result.all())
        
        if not units:
            await callback.message.edit_text(
                f"❌ {level} darajasida Unitlar topilmadi."
            )
            await callback.answer()
            await state.clear()
            return
        
        await state.update_data(cefr_level=level)
        await state.set_state(DeleteUnitStates.choosing_unit)
        
        text = f"CEFR daraja: <b>{level}</b>\n\nO'chirmoqchi bo'lgan Unitni tanlang:"
        await callback.message.edit_text(text, reply_markup=build_units_for_deletion_keyboard(units))
        await callback.answer()


@dp.callback_query(DeleteUnitStates.choosing_unit, F.data.startswith("delete_unit:"))
async def delete_unit_choose_unit(callback: CallbackQuery, state: FSMContext) -> None:
    unit_id = int(callback.data.split(":", 1)[1])
    
    user = await get_or_create_user(callback.from_user)
    
    async for session in get_session():
        unit = await session.get(Unit, unit_id)
        if not unit:
            await callback.answer("Unit topilmadi.", show_alert=True)
            await state.clear()
            return
        
        # Get word lists count and total words
        word_lists_stmt = select(WordList).where(WordList.unit_id == unit_id)
        word_lists_result = await session.scalars(word_lists_stmt)
        word_lists = list(word_lists_result.all())
        
        total_words = 0
        for wl in word_lists:
            words_stmt = select(Word).where(Word.word_list_id == wl.id)
            words_result = await session.scalars(words_stmt)
            total_words += len(list(words_result.all()))
        
        await state.update_data(unit_id=unit_id)
        await state.set_state(DeleteUnitStates.confirming_delete)
        
        text = (
            f"⚠️ <b>Unitni o'chirish</b>\n\n"
            f"Nomi: <b>{unit.name}</b>\n"
            f"CEFR daraja: <b>{unit.cefr_level}</b>\n"
            f"Unit raqami: <b>{unit.unit_number}</b>\n"
            f"So'zlar ro'yxatlari: <b>{len(word_lists)}</b>\n"
            f"Jami so'zlar: <b>{total_words}</b>\n\n"
            f"⚠️ Bu Unitni o'chirish barcha so'zlar ro'yxatlarini va so'zlarni ham o'chiradi!\n\n"
            f"Bu Unitni o'chirishni tasdiqlaysizmi?"
        )
        
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Ha, o'chirish", callback_data="unit_delete_confirm"),
                    InlineKeyboardButton(text="❌ Yo'q", callback_data="unit_delete_cancel"),
                ]
            ]
        )
        
        await callback.message.edit_text(text, reply_markup=keyboard)
        await callback.answer()


@dp.callback_query(DeleteUnitStates.choosing_unit, F.data == "unit_delete_cancel")
async def delete_unit_cancel_selection(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text("❌ Bekor qilindi.")
    await callback.answer()
    await state.clear()


@dp.callback_query(DeleteUnitStates.confirming_delete, F.data == "unit_delete_confirm")
async def delete_unit_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    unit_id = data.get("unit_id")
    
    if not unit_id:
        await callback.answer("Xatolik: Unit ID topilmadi.", show_alert=True)
        await state.clear()
        return
    
    async for session in get_session():
        unit = await session.get(Unit, unit_id)
        if not unit:
            await callback.answer("Unit topilmadi.", show_alert=True)
            await state.clear()
            return
        
        # Get counts before deletion
        word_lists_stmt = select(WordList).where(WordList.unit_id == unit_id)
        word_lists_result = await session.scalars(word_lists_stmt)
        word_lists = list(word_lists_result.all())
        
        total_words = 0
        for wl in word_lists:
            words_stmt = select(Word).where(Word.word_list_id == wl.id)
            words_result = await session.scalars(words_stmt)
            total_words += len(list(words_result.all()))
        
        unit_name = unit.name
        unit_level = unit.cefr_level
        
        # Delete unit (cascade will delete word_lists and words)
        await session.delete(unit)
        await session.commit()
        
        await callback.message.edit_text(
            f"✅ Unit muvaffaqiyatli o'chirildi!\n\n"
            f"Nomi: <b>{unit_name}</b>\n"
            f"CEFR daraja: <b>{unit_level}</b>\n"
            f"O'chirilgan so'zlar ro'yxatlari: <b>{len(word_lists)}</b>\n"
            f"O'chirilgan so'zlar: <b>{total_words}</b>"
        )
        await callback.answer("Unit o'chirildi.")
        await state.clear()


@dp.callback_query(DeleteUnitStates.confirming_delete, F.data == "unit_delete_cancel")
async def delete_unit_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text("❌ O'chirish bekor qilindi.")
    await callback.answer()
    await state.clear()


# ========== DELETE DEGREE HANDLERS ==========

def build_degrees_for_deletion_keyboard() -> InlineKeyboardMarkup:
    """Build keyboard for selecting degree (CEFR level) to delete."""
    buttons = []
    
    # Group levels in rows of 3
    for i in range(0, len(CEFR_LEVELS), 3):
        row_levels = CEFR_LEVELS[i:i+3]
        buttons.append([
            InlineKeyboardButton(text=level, callback_data=f"delete_degree:{level}")
            for level in row_levels
        ])
    
    buttons.append([InlineKeyboardButton(text="❌ Bekor qilish", callback_data="degree_delete_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@dp.message(Command("delete_degree"))
async def cmd_delete_degree(message: Message, state: FSMContext) -> None:
    user = await get_or_create_user(message.from_user)
    
    if not has_admin_permission(user):
        await message.answer("Bu buyruq faqat adminlar uchun.")
        return
    
    await state.set_state(DeleteDegreeStates.choosing_degree)
    await message.answer(
        "⚠️ <b>Degree (CEFR daraja)ni o'chirish</b>\n\n"
        "Bu amal barcha Unitlarni, so'zlar ro'yxatlarini va so'zlarni o'chiradi!\n\n"
        "O'chirmoqchi bo'lgan CEFR darajasini tanlang:",
        reply_markup=build_degrees_for_deletion_keyboard()
    )


@dp.callback_query(DeleteDegreeStates.choosing_degree, F.data.startswith("delete_degree:"))
async def delete_degree_choose_degree(callback: CallbackQuery, state: FSMContext) -> None:
    degree = callback.data.split(":", 1)[1]
    
    async for session in get_session():
        # Get all units for this degree
        units_stmt = select(Unit).where(Unit.cefr_level == degree)
        units_result = await session.scalars(units_stmt)
        units = list(units_result.all())
        
        if not units:
            await callback.message.edit_text(
                f"❌ {degree} darajasida Unitlar topilmadi."
            )
            await callback.answer()
            await state.clear()
            return
        
        # Count word lists and words
        total_word_lists = 0
        total_words = 0
        
        for unit in units:
            word_lists_stmt = select(WordList).where(WordList.unit_id == unit.id)
            word_lists_result = await session.scalars(word_lists_stmt)
            word_lists = list(word_lists_result.all())
            total_word_lists += len(word_lists)
            
            for wl in word_lists:
                words_stmt = select(Word).where(Word.word_list_id == wl.id)
                words_result = await session.scalars(words_stmt)
                total_words += len(list(words_result.all()))
        
        await state.update_data(degree=degree)
        await state.set_state(DeleteDegreeStates.confirming_delete)
        
        text = (
            f"⚠️ <b>Degree (CEFR daraja)ni o'chirish</b>\n\n"
            f"CEFR daraja: <b>{degree}</b>\n"
            f"Unitlar soni: <b>{len(units)}</b>\n"
            f"So'zlar ro'yxatlari: <b>{total_word_lists}</b>\n"
            f"Jami so'zlar: <b>{total_words}</b>\n\n"
            f"⚠️ Bu Degree ni o'chirish barcha Unitlarni, so'zlar ro'yxatlarini va so'zlarni ham o'chiradi!\n\n"
            f"Bu Degree ni o'chirishni tasdiqlaysizmi?"
        )
        
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Ha, o'chirish", callback_data="degree_delete_confirm"),
                    InlineKeyboardButton(text="❌ Yo'q", callback_data="degree_delete_cancel"),
                ]
            ]
        )
        
        await callback.message.edit_text(text, reply_markup=keyboard)
        await callback.answer()


@dp.callback_query(DeleteDegreeStates.choosing_degree, F.data == "degree_delete_cancel")
async def delete_degree_cancel_selection(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text("❌ Bekor qilindi.")
    await callback.answer()
    await state.clear()


@dp.callback_query(DeleteDegreeStates.confirming_delete, F.data == "degree_delete_confirm")
async def delete_degree_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    degree = data.get("degree")
    
    if not degree:
        await callback.answer("Xatolik: Degree topilmadi.", show_alert=True)
        await state.clear()
        return
    
    async for session in get_session():
        # Get all units for this degree
        units_stmt = select(Unit).where(Unit.cefr_level == degree)
        units_result = await session.scalars(units_stmt)
        units = list(units_result.all())
        
        if not units:
            await callback.answer("Bu Degree da Unitlar topilmadi.", show_alert=True)
            await state.clear()
            return
        
        # Count before deletion
        total_word_lists = 0
        total_words = 0
        
        for unit in units:
            word_lists_stmt = select(WordList).where(WordList.unit_id == unit.id)
            word_lists_result = await session.scalars(word_lists_stmt)
            word_lists = list(word_lists_result.all())
            total_word_lists += len(word_lists)
            
            for wl in word_lists:
                words_stmt = select(Word).where(Word.word_list_id == wl.id)
                words_result = await session.scalars(words_stmt)
                total_words += len(list(words_result.all()))
        
        # Delete all units (cascade will delete word_lists and words)
        for unit in units:
            await session.delete(unit)
        
        await session.commit()
        
        await callback.message.edit_text(
            f"✅ Degree muvaffaqiyatli o'chirildi!\n\n"
            f"CEFR daraja: <b>{degree}</b>\n"
            f"O'chirilgan Unitlar: <b>{len(units)}</b>\n"
            f"O'chirilgan so'zlar ro'yxatlari: <b>{total_word_lists}</b>\n"
            f"O'chirilgan so'zlar: <b>{total_words}</b>"
        )
        await callback.answer("Degree o'chirildi.")
        await state.clear()


@dp.callback_query(DeleteDegreeStates.confirming_delete, F.data == "degree_delete_cancel")
async def delete_degree_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text("❌ O'chirish bekor qilindi.")
    await callback.answer()
    await state.clear()


async def main() -> None:
    await init_db()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())


