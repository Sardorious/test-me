from aiogram.fsm.state import State, StatesGroup


class RegistrationStates(StatesGroup):
    waiting_first_name = State()
    waiting_last_name = State()
    waiting_phone = State()
    choosing_cefr = State()
    choosing_direction = State()


class TestStates(StatesGroup):
    choosing_level = State()
    choosing_direction = State()
    choosing_count = State()
    answering = State()


class AdminStates(StatesGroup):
    waiting_teacher_username = State()


class UploadWordsStates(StatesGroup):
    choosing_level = State()
    waiting_file = State()


class DeleteWordsStates(StatesGroup):
    choosing_level = State()
    choosing_wordlist = State()
    confirming_delete = State()


