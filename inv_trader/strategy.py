#!/usr/bin/env python3
# -------------------------------------------------------------------------------------------------
# <copyright file="strategy.py" company="Invariance Pte">
#  Copyright (C) 2018 Invariance Pte. All rights reserved.
#  The use of this source code is governed by the license as found in the LICENSE.md file.
#  http://www.invariance.com
# </copyright>
# -------------------------------------------------------------------------------------------------

import abc
import inspect
import uuid

from collections import deque
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Callable, Deque, Dict, List
from threading import Timer
from sched import scheduler
from uuid import UUID

from inv_trader.core.precondition import Precondition
from inv_trader.core.logger import Logger, LoggingAdapter
from inv_trader.model.account import Account
from inv_trader.model.enums import OrderSide, MarketPosition
from inv_trader.model.events import Event, AccountEvent, OrderEvent
from inv_trader.model.events import OrderFilled, OrderPartiallyFilled
from inv_trader.model.events import TimeEvent
from inv_trader.model.objects import Symbol, Tick, BarType, Bar
from inv_trader.model.order import Order, OrderIdGenerator
from inv_trader.model.position import Position

# Constants
OrderId = str
PositionId = str
Label = str
Indicator = object


class TradeStrategy:
    """
    The abstract base class for all trade strategies.
    """

    __metaclass__ = abc.ABCMeta

    def __init__(self,
                 label: str=None,
                 order_id_tag: str=None,
                 bar_capacity=1000,
                 logger: Logger=None):
        """
        Initializes a new instance of the TradeStrategy abstract class.

        :param: label: The unique label for the strategy (can be None).
        :param: order_id_tag: The unique order identifier tag for the strategy (can be None).
        :param: bar_capacity: The capacity for the internal bar deque(s).
        :param: logger: The logger (can be None, and will print).
        :raises: ValueError: If the label is an invalid string.
        :raises: ValueError: If the order_id_tag is an invalid string.
        :raises: ValueError: If the bar_capacity is not positive (> 0).
        """
        if label is None:
            label = '001'
        if order_id_tag is None:
            order_id_tag = '001'
        Precondition.valid_string(label, 'label')
        Precondition.valid_string(order_id_tag, 'order_id_tag')
        Precondition.positive(bar_capacity, 'bar_capacity')

        self._name = self.__class__.__name__
        self._label = label
        self._id = uuid.uuid4()
        self._order_id_generator = OrderIdGenerator(order_id_tag)
        self._bar_capacity = bar_capacity
        if logger is None:
            self._log = LoggingAdapter(f"{self._name}-{self._label}")
        else:
            self._log = LoggingAdapter(f"{self._name}-{self._label}", logger)
        self._is_running = False
        self._scheduler = scheduler()
        self._ticks = {}                 # type: Dict[Symbol, Tick]
        self._bars = {}                  # type: Dict[BarType, Deque[Bar]]
        self._indicators = {}            # type: Dict[BarType, List[Indicator]]
        self._indicator_updaters = {}    # type: Dict[BarType, List[IndicatorUpdater]]
        self._indicator_index = {}       # type: Dict[Label, Indicator]
        self._order_book = {}            # type: Dict[OrderId, Order]
        self._order_position_index = {}  # type: Dict[OrderId, PositionId]
        self._position_book = {}         # type: Dict[PositionId, Position or None]
        self._account = None  # Initialized with registered with execution client.
        self._exec_client = None

        self._log.info(f"Initialized.")

    def __eq__(self, other) -> bool:
        """
        Override the default equality comparison.
        """
        if isinstance(other, self.__class__):
            return str(self) == str(other)
        else:
            return False

    def __ne__(self, other):
        """
        Override the default not-equals comparison.
        """
        return not self.__eq__(other)

    def __hash__(self):
        """"
        Override the default hash implementation.
        """
        return hash((self.name, self.label))

    def __str__(self) -> str:
        """
        :return: The str() string representation of the strategy.
        """
        return f"{self._name}-{self._label}"

    def __repr__(self) -> str:
        """
        :return: The repr() string representation of the strategy.
        """
        return f"<{str(self)} object at {id(self)}>"

    @abc.abstractmethod
    def on_start(self):
        """
        Called when the strategy is started.
        """
        # Raise exception if not overridden in implementation.
        raise NotImplementedError("Method must be implemented in the strategy (or just add pass).")

    @abc.abstractmethod
    def on_tick(self, tick: Tick):
        """
        Called when a tick is received by the strategy.

        :param tick: The tick received.
        """
        # Raise exception if not overridden in implementation.
        raise NotImplementedError("Method must be implemented in the strategy (or just add pass).")

    @abc.abstractmethod
    def on_bar(self, bar_type: BarType, bar: Bar):
        """
        Called when a bar is received by the strategy.

        :param bar_type: The bar type received.
        :param bar: The bar received.
        """
        # Raise exception if not overridden in implementation.
        raise NotImplementedError("Method must be implemented in the strategy (or just add pass).")

    @abc.abstractmethod
    def on_event(self, event: Event):
        """
        Called when an event is received by the strategy.

        :param event: The event received.
        """
        # Raise exception if not overridden in implementation.
        raise NotImplementedError("Method must be implemented in the strategy (or just add pass).")

    @abc.abstractmethod
    def on_stop(self):
        """
        Called when the strategy is stopped.
        """
        # Raise exception if not overridden in implementation.
        raise NotImplementedError("Method must be implemented in the strategy (or just add pass).")

    @abc.abstractmethod
    def on_reset(self):
        """
        Called when the strategy is reset.
        """
        # Raise exception if not overridden in implementation.
        raise NotImplementedError("Method must be implemented in the strategy (or just add pass).")

    @property
    def name(self) -> str:
        """
        :return: The name of the strategy.
        """
        return self._name

    @property
    def label(self) -> str:
        """
        :return: The label of the strategy.
        """
        return self._label

    @property
    def id(self) -> UUID:
        """
        :return: The unique identifier of the strategy.
        """
        return self._id

    @property
    def is_running(self) -> bool:
        """
        :return: A value indicating whether the strategy is running.
        """
        return self._is_running

    @property
    def log(self) -> LoggingAdapter:
        """
        :return: The logging adapter.
        """
        return self._log

    @property
    def all_indicators(self) -> Dict[BarType, List[Indicator]]:
        """
        :return: The indicators dictionary for the strategy.
        """
        return self._indicators

    @property
    def all_bars(self) -> Dict[BarType, Deque[Bar]]:
        """
        :return: The bars dictionary for the strategy.
        """
        return self._bars

    @property
    def ticks(self) -> Dict[Symbol, Tick]:
        """
        :return: The internally held ticks dictionary for the strategy
        """
        return self._ticks

    @property
    def orders(self) -> Dict[OrderId, Order]:
        """
        :return: The entire order book for the strategy
        """
        return self._order_book

    @property
    def positions(self) -> Dict[PositionId, Position]:
        """
        :return: The entire position book for the strategy.
        """
        return self._position_book

    @property
    def account(self) -> Account or None:
        """
        :return: The strategies account (initialized once registered with execution client).
        """
        return self._account

    def start(self):
        """
        Starts the trade strategy and calls the on_start() method.
        """
        self._exec_client.collateral_inquiry()

        self._log.info(f"Starting...")
        self._is_running = True
        self.on_start()
        self._scheduler.run()
        self._log.info(f"Running...")

    def stop(self):
        """
        Stops the trade strategy and calls the on_stop() method.
        """
        self._log.info(f"Stopping...")
        self.on_stop()
        self._is_running = False
        self._log.info(f"Stopped.")

    def reset(self):
        """
        Reset the trade strategy by clearing all stateful internal values and
        returning it to a fresh state (strategy must not be running).
        """
        if self._is_running:
            self._log.warning(f"Cannot reset a running strategy...")
            return

        self._ticks = {}  # type: Dict[Symbol, Tick]
        self._bars = {}   # type: Dict[BarType, List[Bar]]

        # Reset all indicators.
        for indicator_list in self._indicators.values():
            [indicator.reset() for indicator in indicator_list]

        self.on_reset()
        self._log.info(f"Reset.")

    def indicators(self, bar_type: BarType) -> List[Indicator]:
        """
        Get the indicators list for the given bar type.

        :param: The bar type for the indicators list.
        :return: The internally held indicators for the given bar type.
        :raises: KeyError: If the strategies indicators dictionary does not contain the given bar_type.
        """
        if bar_type not in self._indicators:
            raise KeyError(f"The indicators dictionary does not contain {bar_type}.")

        return self._indicators[bar_type]

    def indicator(self, label: str) -> Indicator:
        """
        Get the indicator for the given unique label.

        :param: label: The unique label for the indicator.
        :return: The internally held indicator for the given unique label.
        :raises: KeyError: If the strategies indicator dictionary does not contain the given label.
        """
        Precondition.valid_string(label, 'label')

        if label not in self._indicator_index:
            raise KeyError(f"The indicator dictionary does not contain the label {label}.")

        return self._indicator_index[label]

    def bars(self, bar_type: BarType) -> Deque[Bar]:
        """
        Get the bars for the given bar type.

        :param bar_type: The bar type to get.
        :return: The list of bars.
        :raises: KeyError: If the strategies bars dictionary does not contain the bar type.
        """
        if bar_type not in self._bars:
            raise KeyError(f"The bars dictionary does not contain {bar_type}.")

        return self._bars[bar_type]

    def bar(
            self,
            bar_type: BarType,
            index: int) -> Bar:
        """
        Get the bar for the given bar type at the given index.

        :param bar_type: The bar type to get.
        :param index: The index to get (can be positive or negative but not out of range).
        :return: The bar (if found).
        :raises: KeyError: If the strategies bars dictionary does not contain the bar type.
        :raises: IndexError: If the strategies bars dictionary does not contain a bar at the given index.
        """
        if bar_type not in self._bars:
            raise KeyError(f"The bars dictionary does not contain {bar_type}.")

        return self._bars[bar_type][index]

    def last_tick(self, symbol: Symbol) -> Tick:
        """
        Get the last tick held for the given parameters.

        :param symbol: The last tick symbol.
        :return: The tick object.
        :raises: KeyError: If the strategies tick dictionary does not contain a tick for the given symbol.
        """
        if symbol not in self._ticks:
            raise KeyError(f"The ticks dictionary does not contain {symbol}.")

        return self._ticks[symbol]

    def order(self, order_id: OrderId) -> Order:
        """
        Get the order from the order book with the given order_id.

        :param order_id: The order identifier.
        :return: The order (if found).
        :raises: KeyError: If the strategies order book does not contain the order with the given id.
        """
        Precondition.valid_string(order_id, 'order_id')

        if order_id not in self._order_book:
            raise KeyError(f"The order book does not contain the order with id {order_id}.")

        return self._order_book[order_id]

    def position(self, position_id: PositionId) -> Position:
        """
        Get the position from the positions dictionary for the given position id.

        :param position_id: The positions identifier.
        :return: The position (if found).
        :raises: KeyError: If the strategies positions dictionary does not contain the given position_id.
        """
        Precondition.valid_string(position_id, 'position_id')

        if position_id not in self._position_book:
            raise KeyError(
                f"The positions dictionary does not contain the position {position_id}.")

        return self._position_book[position_id]

    def register_indicator(
            self,
            bar_type: BarType,
            indicator: Indicator,
            update_method: Callable,
            label: str):
        """
        Add the given indicator to the strategy. The indicator must be from the
        inv_indicators package. Once added it will receive bars of the given
        bar type.

        :param bar_type: The indicators bar type.
        :param indicator: The indicator to set.
        :param update_method: The update method for the indicator.
        :param label: The unique label for this indicator.
        :raises: ValueError: If the label is an invalid string.
        :raises: KeyError: If the given indicator label is not unique for this strategy.
        """
        Precondition.valid_string(label, 'label')

        if label in self._indicator_index.keys():
            raise KeyError("The indicator label must be unique for this strategy.")

        if bar_type not in self._indicators:
            self._indicators[bar_type] = []  # type: List[Indicator]
        self._indicators[bar_type].append(indicator)

        if bar_type not in self._indicator_updaters:
            self._indicator_updaters[bar_type] = []  # type: List[IndicatorUpdater]
        self._indicator_updaters[bar_type].append(IndicatorUpdater(update_method))

        self._indicator_index[label] = indicator

    def set_time_alert(
            self,
            label: str,
            alert_time: datetime,
            priority: int=1):
        """
        Set a time alert for the given time. When the time is reached and the
        strategy is running, on_event() is passed the TimeEvent containing the
        alerts unique label.

        A priority can be set in the case that time events occur simultaneously,
        the events will be raised in the order of priority with the lower the
        number the higher the priority.

        :param label: The unique label for the alert.
        :param alert_time: The time for the alert.
        :param priority: The priority for the alert (lower numbers are higher priority).
        :raises: ValueError: If the label is an invalid string.
        :raises: ValueError: If the alert_time is not greater than the current time (UTC).
        :raises: ValueError: If the priority is negative (< 0).
        """
        Precondition.valid_string(label, 'label')
        Precondition.true(alert_time > datetime.utcnow(), 'alert_time > datetime.utcnow()')
        Precondition.not_negative(priority, 'priority')

        self._scheduler.enterabs(
            time=(alert_time - datetime.utcnow()).total_seconds(),
            priority=priority,
            action=self._raise_time_event,
            argument=(label, alert_time))

    def set_timer(
            self,
            label: str,
            start_time: datetime,
            interval: timedelta,
            priority: int=1,
            repeat: bool=False):
        """
        Set a timer with the given interval (time delta). The timer will run once
        the strategy is started and the start time is reached. When the interval
        is reached on_event() is passed the TimeEvent containing the timers
        unique label.

        A priority can be set in the case that time events occur simultaneously,
        the events will be raised in the order of priority with the lower the
        number the higher the priority (not applicable to repeating timers).

        Optionally the timer can be run repeatedly whilst the strategy is running.

        :param label: The unique label for the timer.
        :param start_time: The time the timer should start at.
        :param interval: The time delta interval for the timer.
        :param priority: The priority for the alert (lower numbers are higher priority,
        not applicable to repeating timers).
        :param repeat: The option for the timer to repeat until the strategy is stopped
        (no priority).
        :raises: ValueError: If the label is an invalid string.
        :raises: ValueError: If the alert_time is not greater than the current time (UTC).
        :raises: ValueError: If the priority is negative (< 0).
        """
        Precondition.valid_string(label, 'label')
        Precondition.true(start_time > datetime.utcnow(), 'start_time > datetime.utcnow()')
        Precondition.not_negative(priority, 'priority')

        alert_time = start_time + interval
        delay = (alert_time - datetime.utcnow()).total_seconds()
        if repeat:
            timer = Timer(
                interval=delay,
                function=self._repeating_timer,
                args=[label, alert_time, interval])
            timer.start()
        else:
            self._scheduler.enterabs(
                time=delay,
                priority=priority,
                action=self._raise_time_event,
                argument=(label, alert_time))

    def generate_order_id(self, symbol: Symbol) -> OrderId:
        """
        Generates a unique order identifier with the given symbol.

        :param symbol: The order symbol.
        :return: The unique order identifier.
        """
        return self._order_id_generator.generate(symbol)

    def get_opposite_side(self, side: OrderSide) -> OrderSide:
        """
        Get the opposite order side from the original side given.

        :param side: The original order side.
        :return: The opposite order side.
        """
        return OrderSide.BUY if side is OrderSide.SELL else OrderSide.SELL

    def get_flatten_side(self, market_position: MarketPosition) -> OrderSide:
        """
        Get the order side needed to flatten the position from the given market position.

        :param market_position: The market position to flatten.
        :return: The order side to flatten.
        :raises: KeyError: If the given market position is flat.
        """
        if market_position is MarketPosition.LONG:
            return OrderSide.SELL
        elif market_position is MarketPosition.SHORT:
            return OrderSide.BUY
        else:
            raise ValueError("Cannot flatten a FLAT position.")

    def submit_order(
            self,
            order: Order,
            position_id: PositionId):
        """
        Send a submit order request with the given order to the execution client.

        :param order: The order to submit.
        :param position_id: The position id to associate with this order.
        :raises: ValueError: If the position_id is an invalid string.
        :raises: KeyError: If the order_id is already contained in the order book (must be unique).
        """
        Precondition.valid_string(position_id, 'position_id')

        if order.id in self._order_book:
            raise KeyError(
                "The order id is already contained in the order book (must be unique).")

        self._order_book[order.id] = order
        self._order_position_index[order.id] = position_id

        self._log.info(f"Submitting {order}")
        self._exec_client.submit_order(order, self._id)

    def cancel_order(
            self,
            order: Order,
            cancel_reason: str='NONE'):
        """
        Send a cancel order request for the given order to the execution client.

        :param order: The order to cancel.
        :param cancel_reason: The reason for cancellation (will be logged).
        :raises: ValueError: If the cancel_reason is an invalid string.
        :raises: KeyError: If the order_id was not found in the order book.
        """
        Precondition.valid_string(cancel_reason, 'cancel_reason')

        if order.id not in self._order_book.keys():
            raise KeyError("The order id was not found in the order book.")

        self._log.info(f"Cancelling {order}")
        self._exec_client.cancel_order(order, cancel_reason)

    def modify_order(
            self,
            order: Order,
            new_price: Decimal):
        """
        Send a modify order request for the given order with the given new price
        to the execution client.

        :param order: The order to modify.
        :param new_price: The new price for the given order.
        :raises: ValueError: If the new_price is not positive (> 0).
        :raises: KeyError: If order_id was not found in the order book.
        """
        Precondition.positive(new_price, 'new_price')

        if order.id not in self._order_book.keys():
            raise KeyError("The order id was not found in the order book.")

        self._log.info(f"Modifying {order} with new price {new_price}")
        self._exec_client.modify_order(order, new_price)

    def _register_execution_client(self, client):
        """
        Register the execution client with the strategy.

        :param client: The execution client to register.
        :raises: ValueError: If client is None.
        :raises: TypeError: If client does not inherit from ExecutionClient.
        """
        if client is None:
            raise ValueError("The client cannot be None.")
        if client.__class__.__mro__[-2].__name__ != 'ExecutionClient':
            raise TypeError("The client must inherit from the ExecutionClient base class.")

        self._exec_client = client
        self._account = client.account

    def _update_ticks(self, tick: Tick):
        """"
        Updates the last held tick with the given tick then calls the on_tick
        method for the inheriting class.

        :param tick: The tick received.
        """
        # Update the internal ticks.
        self._ticks[tick.symbol] = tick

        # Calls on_tick() if the strategy is running.
        if self._is_running:
            self.on_tick(tick)

    def _update_bars(
            self,
            bar_type: BarType,
            bar: Bar):
        """"
        Updates the internal dictionary of bars with the given bar, then calls the
        on_bar method for the inheriting class.

        :param bar_type: The bar type received.
        :param bar: The bar received.
        """
        # Update the internal bars.
        if bar_type not in self._bars:
            self._bars[bar_type] = deque(maxlen=self._bar_capacity)  # type: Deque[Bar]
        self._bars[bar_type].append(bar)

        # Update the internal indicators.
        if bar_type in self._indicators:
            self._update_indicators(bar_type, bar)

        # Calls on_bar() if the strategy is running.
        if self._is_running:
            self.on_bar(bar_type, bar)

    def _update_indicators(
            self,
            bar_type: BarType,
            bar: Bar):
        """
        Updates the internal indicators of the given bar type with the given bar.

        :param bar_type: The bar type to update.
        :param bar: The bar for update.
        """
        if bar_type not in self._indicators:
            # No indicators to update with this bar.
            return

        # For each updater matching the given bar type -> update with the bar.
        [updater.update(bar) for updater in self._indicator_updaters[bar_type]]

    def _update_events(self, event: Event):
        """
        Updates the strategy with the given event.

        :param event: The event received.
        """
        self._log.info(str(event))

        # Order events.
        if isinstance(event, OrderEvent):
            order_id = event.order_id
            if order_id in self._order_book:
                self._order_book[order_id].apply(event)
            else:
                self._log.warning("The event order id not found in the order book.")

            # Position events.
            if isinstance(event, OrderFilled) or isinstance(event, OrderPartiallyFilled):
                if event.order_id in self._order_position_index:
                    position_id = self._order_position_index[event.order_id]

                    if position_id not in self._position_book:
                        opened_position = Position(
                            event.symbol,
                            position_id,
                            event.execution_time)
                        self._position_book[position_id] = opened_position
                        self._position_book[position_id].apply(event)
                        self._log.info(f"Opened {opened_position}")
                    else:
                        self._position_book[position_id].apply(event)

                        # If this order event exits the position then save to the database,
                        # and remove from list.
                        if self._position_book[position_id].is_exited:
                            # TODO: Save to database.
                            closed_position = self._position_book[position_id]
                            self._position_book.pop(position_id)
                            self._log.info(f"Closed {closed_position}")
                        else:
                            self._log.info(f"Modified {self._position_book[position_id]}")
                else:
                    self._log.warning("The event order id not found in the order position index.")

        # Account Events.
        elif isinstance(event, AccountEvent):
            self._account.apply(event)

        # Calls on_event() if the strategy is running.
        if self._is_running:
            self.on_event(event)

    def _raise_time_event(
            self,
            label: str,
            alert_time: datetime):
        """
        Create a new time event and pass it into the on_event method.
        """
        self.on_event(TimeEvent(label, uuid.uuid4(), alert_time))

    def _repeating_timer(
            self,
            label: str,
            alert_time: datetime,
            interval: timedelta):
        """
        Create a new time event and pass it into the on_event method.
        Then start a timer for the next time event.
        """
        self.on_event(TimeEvent(label, uuid.uuid4(), alert_time))

        if self._is_running:
            next_alert_time = alert_time + interval
            delay = (next_alert_time - datetime.utcnow()).total_seconds()
            timer = Timer(
                interval=delay,
                function=self._repeating_timer,
                args=[label, alert_time, interval])
            timer.start()


# Constants
POINT = 'point'
PRICE = 'price'
MID = 'mid'
OPEN = 'open'
HIGH = 'high'
LOW = 'low'
CLOSE = 'close'
VOLUME = 'volume'
TIMESTAMP = 'timestamp'


class IndicatorUpdater:
    """
    Provides an adapter for updating an indicator with a bar. When instantiated
    with a live indicator update method, the updater will inspect the method and
    construct the required parameter list for updates.
    """

    def __init__(self, update_method: Callable):
        """
        Initializes a new instance of the IndicatorUpdater class.

        :param update_method: The indicators update method.
        """
        self._update_method = update_method
        self._update_params = []

        param_map = {
            POINT: CLOSE,
            PRICE: CLOSE,
            MID: CLOSE,
            OPEN: OPEN,
            HIGH: HIGH,
            LOW: LOW,
            CLOSE: CLOSE,
            TIMESTAMP: TIMESTAMP
        }

        for param in inspect.signature(update_method).parameters:
            self._update_params.append(param_map[param])

    def update(self, bar: Bar):
        """
        Passes the needed values from the given bar to the indicator update
        method as a list of arguments.

        :param bar: The update bar.
        """
        args = [bar.__getattribute__(param) for param in self._update_params]
        self._update_method(*args)
