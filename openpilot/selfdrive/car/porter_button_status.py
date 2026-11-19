"""Display-only feedback for Porter conventional-cruise button failures."""

from opendbc.car.hyundai.porter import supports_porter_button_cruise


def porter_button_unavailable(CP, controller, stock_enabled):
  buttons = getattr(controller, "porter_buttons", None)
  return bool(supports_porter_button_cruise(CP) and stock_enabled and buttons is not None and buttons.unavailable)


def warn_porter_button_unavailable(CP, CS, output, fresh):
  return bool(
    fresh
    and supports_porter_button_cruise(CP)
    and CS.cruiseState.enabled
    and CS.canValid
    and not CS.canTimeout
    and not CS.accFaulted
    and output.porterButtonUnavailable
  )
