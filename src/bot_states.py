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


