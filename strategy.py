#!/usr/bin/env python3
"""
GRVT BTC网格交易策略 - 完整版（按照JS逻辑重构）
集成币安API RSI/ADX技术指标检查
"""
import math
import time
import logging
import asyncio
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta
from dataclasses import dataclass

# 导入您的GrvtTrader类
from grvt_client import GrvtTrader
from config import *
from binance_client import BinanceClient
from technical_analyzer import TechnicalAnalyzer

logger = logging.getLogger(__name__)


@dataclass
class MarketData:
    """市场数据容器"""
    ask_price: float = 0.0
    bid_price: float = 0.0
    last_price: float = 0.0
    timestamp: int = 0
    existing_sell_orders: List[float] = None
    existing_buy_orders: List[float] = None

    def __post_init__(self):
        if self.existing_sell_orders is None:
            self.existing_sell_orders = []
        if self.existing_buy_orders is None:
            self.existing_buy_orders = []

    @property
    def mid_price(self) -> float:
        """中间价"""
        if self.ask_price > 0 and self.bid_price > 0:
            return (self.ask_price + self.bid_price) / 2
        return self.last_price

    @property
    def spread(self) -> float:
        """买卖价差"""
        if self.ask_price > 0 and self.bid_price > 0:
            return self.ask_price - self.bid_price
        return 0.0


@dataclass
class TradeInfo:
    """交易信息容器"""
    position_btc: float = 0.0
    order_size: float = 0.0
    entry_price: float = 0.0
    unrealized_pnl: float = 0.0


class GridStrategy:
    """网格交易策略核心 - 按照JS逻辑重构"""

    def __init__(self, trader: GrvtTrader):
        self.trader = trader
        self.symbol = GRVT_CONFIG["symbol"]

        # ===== 关键修复：从配置读取订单大小 =====
        self.order_size = TRADING_CONFIG.get("ORDER_SIZE", 0.005)
        logger.info(f"📦 订单大小: {self.order_size} BTC (来自TRADING_CONFIG配置)")

        # 状态跟踪
        self.active_orders = {}  # client_order_id -> order_info
        self.order_history = []
        self.cycle_count = 0
        self.total_pnl = 0.0

        # 风控状态
        self.risk_cooling_down = False
        self.risk_cool_down_end_time = 0
        self.risk_triggered_reason = ""

        # 技术指标相关状态
        self.last_indicators = None
        self.last_market_condition = None
        self.indicators_cache = None
        self.indicators_cache_time = 0

        # 性能跟踪
        self.start_time = time.time()
        self.trades_executed = 0
        self.total_orders_placed = 0

        # 初始化币安客户端和技术分析器
        self._initialize_technical_analysis()

        # 验证配置
        self._validate_config()

        logger.info("✅ 网格策略初始化完成（按照JS逻辑重构）")

    def _validate_config(self):
        """验证配置"""
        logger.info("🔧 配置验证:")
        logger.info(f"  订单大小: {self.order_size} BTC")
        logger.info(f"  总单数: {GRID_STRATEGY_CONFIG.get('TOTAL_ORDERS')}")
        logger.info(f"  卖单比例: {GRID_STRATEGY_CONFIG.get('SELL_RATIO')}")
        logger.info(f"  窗口比例: {GRID_STRATEGY_CONFIG.get('WINDOW_PERCENT')}")
        logger.info(f"  最大倍数: {GRID_STRATEGY_CONFIG.get('MAX_MULTIPLIER')}")

        # 验证关键配置
        if self.order_size <= 0:
            logger.error("❌ 订单大小必须大于0")
            raise ValueError("无效的订单大小配置")

        # 验证买卖比例
        sell_ratio = GRID_STRATEGY_CONFIG.get("SELL_RATIO", 0.5)
        buy_ratio_calculated = 1 - sell_ratio
        logger.info(f"  计算买单比例: {buy_ratio_calculated} (1 - SELL_RATIO)")

        if "BUY_RATIO" in GRID_STRATEGY_CONFIG:
            logger.warning("⚠️  配置中存在BUY_RATIO，建议删除，使用1 - SELL_RATIO计算")

    def _initialize_technical_analysis(self):
        """初始化技术分析模块"""
        if DATA_SOURCE_CONFIG.get("rsi_adx_enabled", False):
            try:
                self.binance_client = BinanceClient()
                self.technical_analyzer = TechnicalAnalyzer()
                logger.info("✅ RSI/ADX技术指标检查模块已启用")
            except Exception as e:
                logger.error(f"❌ 技术指标模块初始化失败，将被禁用: {e}")
                DATA_SOURCE_CONFIG["rsi_adx_enabled"] = False
                self.binance_client = None
                self.technical_analyzer = None
        else:
            logger.info("ℹ️  RSI/ADX技术指标检查已禁用（通过配置）")
            self.binance_client = None
            self.technical_analyzer = None

    def set_order_size(self, size_btc: float):
        """设置订单大小"""
        self.order_size = max(0.001, size_btc)  # 最小0.001 BTC
        logger.info(f"订单大小设置为: {self.order_size} BTC")

    async def get_market_data(self) -> MarketData:
        """获取完整的市场数据 - 简化版"""
        try:
            # 获取最新价格
            ticker = self.trader.get_ticker(self.symbol)
            if not ticker:
                logger.error("get_ticker返回了None")
                raise ValueError("无法获取价格数据：接口返回为空")

            ask_price = ticker.get('ask', 0.0)
            bid_price = ticker.get('bid', 0.0)

            logger.info(f"从接口获取到价格: ask=${ask_price}, bid=${bid_price}")

            # 获取现有订单
            orders = self.get_open_orders()
            sell_orders = []
            buy_orders = []

            for order in orders:
                price = order.get('price', 0.0)
                side = order.get('side', '').lower()

                if price > 0:  # 只处理有效价格的订单
                    if side == 'sell':
                        sell_orders.append(price)
                    elif side == 'buy':
                        buy_orders.append(price)

            logger.info(f"订单统计: 卖单{len(sell_orders)}个, 买单{len(buy_orders)}个")
            if sell_orders:
                logger.info(f"卖单价范围: ${min(sell_orders):.2f} ~ ${max(sell_orders):.2f}")
            if buy_orders:
                logger.info(f"买单价范围: ${min(buy_orders):.2f} ~ ${max(buy_orders):.2f}")

            # 返回MarketData对象
            market_data = MarketData(
                ask_price=float(ask_price),
                bid_price=float(bid_price),
                last_price=float(ticker.get('last', 0.0)),
                timestamp=ticker.get('timestamp', int(time.time() * 1000)),
                existing_sell_orders=sorted(sell_orders),
                existing_buy_orders=sorted(buy_orders, reverse=True)
            )

            logger.info(f"✅ 市场数据组装成功: mid_price=${market_data.mid_price:.2f}")
            return market_data

        except Exception as e:
            logger.error(f"获取市场数据失败: {e}", exc_info=True)
            return MarketData()

    def get_open_orders(self) -> List[Dict]:
        """获取当前所有挂单 - 简化版，直接调用trader的方法"""
        try:
            # 直接调用trader的get_open_orders方法
            orders = self.trader.get_open_orders(self.symbol)
            logger.info(f"通过trader获取到 {len(orders)} 个挂单")
            return orders
        except Exception as e:
            logger.error(f"获取挂单失败: {e}")
            return []

    async def get_trade_info(self) -> TradeInfo:
        """获取交易信息（仓位、订单大小等）"""
        try:
            # 获取仓位
            positions = self.trader.get_positions(self.symbol)
            position_btc = 0.0
            entry_price = 0.0
            unrealized_pnl = 0.0

            if positions:
                for pos in positions:
                    if pos['symbol'] == self.symbol:
                        position_btc = pos['size']
                        entry_price = pos['entry_price']
                        # 假设仓位信息包含未实现盈亏
                        unrealized_pnl = pos.get('unrealized_pnl', 0.0)
                        break

            return TradeInfo(
                position_btc=position_btc,
                order_size=self.order_size,
                entry_price=entry_price,
                unrealized_pnl=unrealized_pnl
            )

        except Exception as e:
            logger.error(f"获取交易信息失败: {e}")
            return TradeInfo()

    async def get_technical_indicators(self) -> Optional[Dict]:
        """
        获取并计算技术指标
        使用缓存避免频繁请求API
        """
        if not DATA_SOURCE_CONFIG.get("rsi_adx_enabled", False):
            return None

        # 检查缓存
        cache_seconds = INDICATOR_CONFIG.get("cache_seconds", 30)
        current_time = time.time()

        if (self.indicators_cache is not None and
                current_time - self.indicators_cache_time < cache_seconds):
            logger.debug("使用缓存的技术指标数据")
            return self.indicators_cache

        try:
            # 1. 从币安获取K线数据
            df = self.binance_client.fetch_ohlcv()
            if df is None or len(df) == 0:
                logger.warning("无法获取币安K线数据")
                return None

            # 2. 计算技术指标
            indicators = self.technical_analyzer.calculate_indicators(df)
            if not indicators:
                logger.warning("技术指标计算失败")
                return None

            # 3. 评估市场状况
            market_condition = self.technical_analyzer.evaluate_market_condition(indicators)

            # 4. 保存结果到缓存
            result = {
                'indicators': indicators,
                'market_condition': market_condition,
                'timestamp': current_time
            }

            self.indicators_cache = result
            self.indicators_cache_time = current_time
            self.last_indicators = indicators
            self.last_market_condition = market_condition

            # 5. 打印指标状态
            logger.info(
                f"📊 技术指标 | RSI: {indicators['rsi']:.2f} | ADX: {indicators['adx']:.2f} | 价格: ${indicators['price']:.2f}")
            logger.info(f"📈 市场评估: {market_condition['market_condition']} - {market_condition['reason']}")

            return result

        except Exception as e:
            logger.error(f"❌ 获取技术指标失败: {e}")
            return None

    async def execute_grid_cycle(self):
        """执行网格交易周期 - 集成技术指标检查"""
        self.cycle_count += 1
        logger.info(f"\n{'=' * 60}")
        logger.info(f"第 {self.cycle_count} 次网格循环 | 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"{'=' * 60}")

        # 1. 检查风控冷却
        if self.check_risk_cooldown():
            logger.info("⏸️ 风控冷却中，跳过本次循环")
            return

        # 2. 检查技术指标（如果启用）- 暂时禁用
        if DATA_SOURCE_CONFIG.get("rsi_adx_enabled", False):
            logger.info("🔍 检查RSI/ADX技术指标...")
            tech_data = await self.get_technical_indicators()

            if tech_data:
                market_condition = tech_data['market_condition']

                # 如果指标不允许交易，触发风控冷却
                if not market_condition['trading_allowed']:
                    logger.warning(f"⛔ 技术指标禁止交易: {market_condition['reason']}")
                    await self.trigger_risk_cooldown(market_condition['reason'])
                    return  # 触发风控，结束本次循环
                else:
                    logger.info(f"✅ 技术指标检查通过: {market_condition['reason']}")
            else:
                # 获取指标失败时，根据风险偏好决定是否继续
                logger.warning("⚠️ 无法获取技术指标，本次循环跳过指标检查")

        # 3. 获取市场数据
        try:
            market_data = await self.get_market_data()
            if not market_data.ask_price or not market_data.bid_price:
                logger.error("❌ 无法获取有效的市场数据")
                return

            logger.info(
                f"💰 市场价格 | 买一: ${market_data.bid_price:.2f} | 卖一: ${market_data.ask_price:.2f} | 中间价: ${market_data.mid_price:.2f}")

        except Exception as e:
            logger.error(f"❌ 获取市场数据失败: {e}")
            await self.trigger_risk_cooldown(f"市场数据获取失败: {str(e)}")
            return

        # 4. 计算目标价格网格
        try:
            result = await self.calculate_target_prices(market_data)

            # 5. 执行撤销订单
            if result["cancel_orders"]:
                logger.info(f"🗑️  执行撤单: {len(result['cancel_orders'])}个订单")
                await self.cancel_distant_orders(result["cancel_orders"])
                await asyncio.sleep(2)  # 等待撤单完成

                # ===== 关键修复：撤单后重新获取市场数据 =====
                logger.info("🔄 撤单后重新获取市场数据...")
                market_data = await self.get_market_data()

                # ===== 关键修复：基于新数据重新计算 =====
                logger.info("🔄 基于新数据重新计算目标价格...")
                result = await self.calculate_target_prices(market_data)

            # 6. 执行新订单
            if result["buy_prices"] or result["sell_prices"]:
                logger.info(f"📤 执行下单: {len(result['buy_prices'])}买 + {len(result['sell_prices'])}卖")
                await self.place_new_orders(
                    result["buy_prices"],
                    result["sell_prices"]
                )
            else:
                logger.info("🔄 无需下新订单，网格状态良好")

            # 7. 更新性能指标
            self.update_performance_metrics()

        except Exception as e:
            logger.error(f"❌ 网格循环执行失败: {e}", exc_info=True)
            await self.trigger_risk_cooldown(f"执行异常: {str(e)}")

    async def calculate_target_prices(self, market_data: MarketData) -> Dict:
        """计算目标价格网格 - 完全按照JS版本逻辑（增强调试）"""
        cfg = GRID_STRATEGY_CONFIG

        # 获取当前仓位信息
        trade_info = await self.get_trade_info()
        position_btc = trade_info.position_btc

        # 计算中间价
        mid_price = market_data.mid_price
        window_size = mid_price * cfg["WINDOW_PERCENT"]
        half_window = window_size / 2
        interval = cfg["BASE_PRICE_INTERVAL"]

        # 计算仓位倍数 - 完全按照JS逻辑
        position_multiplier = abs(position_btc) / max(self.order_size, 0.000001)
        max_multiplier = cfg["MAX_MULTIPLIER"]  # 应该改为15，与JS一致

        # 根据仓位调整买卖比例 - 完全按照JS逻辑
        base_sell_ratio = cfg["SELL_RATIO"]
        base_buy_ratio = 1 - base_sell_ratio  # JS版本是1 - SELL_RATIO

        final_sell_ratio = base_sell_ratio
        final_buy_ratio = base_buy_ratio
        is_at_limit = False

        logger.info(
            f"📊 仓位状态: {position_btc:.4f} BTC | 倍数: {position_multiplier:.1f}x | 开仓大小: {self.order_size:.4f} BTC")

        # 仓位管理逻辑 - 完全按照JS逻辑
        if position_multiplier >= max_multiplier:
            is_at_limit = True
            if position_btc > 0:
                logger.warning(f"🚫 多单已达上限({max_multiplier}x)，停止开多单")
                final_buy_ratio = 0
                final_sell_ratio = 1
            elif position_btc < 0:
                logger.warning(f"🚫 空单已达上限({max_multiplier}x)，停止开空单")
                final_buy_ratio = 1
                final_sell_ratio = 0
        elif position_multiplier > 0:
            reduction_ratio = position_multiplier / max_multiplier

            if position_btc > 0:
                buy_reduction = reduction_ratio * base_buy_ratio
                final_buy_ratio = max(0, base_buy_ratio - buy_reduction)
                final_sell_ratio = 1 - final_buy_ratio
                logger.info(f"⚖️  比例调整: 卖单{final_sell_ratio * 100:.0f}% / 买单{final_buy_ratio * 100:.0f}%")
            elif position_btc < 0:
                sell_reduction = reduction_ratio * base_sell_ratio
                final_sell_ratio = max(0, base_sell_ratio - sell_reduction)
                final_buy_ratio = 1 - final_sell_ratio
                logger.info(f"⚖️  比例调整: 卖单{final_sell_ratio * 100:.0f}% / 买单{final_buy_ratio * 100:.0f}%")
        # 确保比例在合理范围内 - 按照JS逻辑
        if not is_at_limit:
            final_buy_ratio = max(0.1, min(0.9, final_buy_ratio))
            final_sell_ratio = max(0.1, min(0.9, final_sell_ratio))

        logger.info(f"🎯 最终比例: 卖单{final_sell_ratio * 100:.0f}% / 买单{final_buy_ratio * 100:.0f}%")

        # 计算买卖单数量 - 完全按照JS逻辑（使用round，不是int）
        sell_count = round(cfg["TOTAL_ORDERS"] * final_sell_ratio)  # JS使用Math.round
        buy_count = cfg["TOTAL_ORDERS"] - sell_count

        # 验证订单数量
        if sell_count + buy_count != cfg["TOTAL_ORDERS"]:
            logger.warning(f"⚠️ 订单数量不匹配: 卖{sell_count} + 买{buy_count} ≠ 总{cfg['TOTAL_ORDERS']}")
            buy_count = cfg["TOTAL_ORDERS"] - sell_count  # 调整确保总和正确

        logger.info(f"订单数量: {sell_count}卖 + {buy_count}买 = {sell_count + buy_count}总")

        # 计算卖单价格（从卖一价上方开始）- 完全按照JS逻辑
        sell_start = math.ceil((market_data.ask_price + cfg["SAFE_GAP"]) / interval) * interval
        ideal_sell_prices = []
        for i in range(sell_count):
            price = sell_start + i * interval
            if price > mid_price + half_window + cfg["MAX_DRIFT_BUFFER"]:
                break
            ideal_sell_prices.append(round(price, 2))

        # 计算买单价格（从买一价下方开始）- 完全按照JS逻辑
        buy_end = ((market_data.bid_price - cfg["SAFE_GAP"]) // interval) * interval
        ideal_buy_prices = []
        for i in range(buy_count):
            price = buy_end - i * interval
            if price < mid_price - half_window - cfg["MAX_DRIFT_BUFFER"]:
                break
            if price < cfg["MIN_VALID_PRICE"]:
                break
            ideal_buy_prices.append(round(price, 2))

        # === 价格匹配容差 ===
        PRICE_TOLERANCE = 0.5

        # 获取现有订单的详细日志
        logger.info(f"🔄 开始匹配现有订单...")
        logger.info(f"  现有卖单数量: {len(market_data.existing_sell_orders)}")
        logger.info(f"  现有买单数量: {len(market_data.existing_buy_orders)}")
        logger.info(f"  目标卖单数量: {len(ideal_sell_prices)}")
        logger.info(f"  目标买单数量: {len(ideal_buy_prices)}")

        # 打印详细的现有订单信息
        if market_data.existing_sell_orders:
            logger.info(f"  现有卖单价（全部）: {[f'${p:.2f}' for p in market_data.existing_sell_orders]}")
        else:
            logger.info("  现有卖单: 无")

        if market_data.existing_buy_orders:
            logger.info(f"  现有买单价（全部）: {[f'${p:.2f}' for p in market_data.existing_buy_orders]}")
        else:
            logger.info("  现有买单: 无")

        if ideal_sell_prices:
            logger.debug(f"  目标卖单价: {[f'${p:.2f}' for p in ideal_sell_prices]}")
        if ideal_buy_prices:
            logger.debug(f"  目标买单价: {[f'${p:.2f}' for p in ideal_buy_prices]}")

        # === 核心：完全按照JS版本的订单匹配和撤销逻辑 ===

        # 1. 找出需要新下的订单（不在现有订单中的目标订单）
        new_sell_prices = []
        new_buy_prices = []

        # 使用价格容差匹配
        logger.debug("匹配卖单...")
        for target_price in ideal_sell_prices:
            found = False
            for existing_price in market_data.existing_sell_orders:
                price_diff = abs(existing_price - target_price)
                if price_diff <= PRICE_TOLERANCE:
                    logger.debug(f"    卖单匹配: ${target_price:.2f} ≈ ${existing_price:.2f} (差: ${price_diff:.2f})")
                    found = True
                    break
            if not found:
                new_sell_prices.append(target_price)
                logger.debug(f"    卖单需新增: ${target_price:.2f}")

        logger.debug("匹配买单...")
        for target_price in ideal_buy_prices:
            found = False
            for existing_price in market_data.existing_buy_orders:
                price_diff = abs(existing_price - target_price)
                if price_diff <= PRICE_TOLERANCE:
                    logger.debug(f"    买单匹配: ${target_price:.2f} ≈ ${existing_price:.2f} (差: ${price_diff:.2f})")
                    found = True
                    break
            if not found:
                new_buy_prices.append(target_price)
                logger.debug(f"    买单需新增: ${target_price:.2f}")

        # 2. 计算需要撤销的远单（完全按照JS逻辑）
        cancel_orders = []

        # 计算当前总订单数和目标总订单数
        current_total = len(market_data.existing_sell_orders) + len(market_data.existing_buy_orders)
        target_total = len(ideal_sell_prices) + len(ideal_buy_prices)

        logger.debug(f"订单总数: 当前={current_total}, 目标={target_total}")
        logger.debug(f"卖单数: 当前={len(market_data.existing_sell_orders)}, 目标={sell_count}")
        logger.debug(f"买单数: 当前={len(market_data.existing_buy_orders)}, 目标={buy_count}")

        # JS逻辑：只有当当前订单数超过目标，或者卖单/买单数量超过目标时，才考虑撤单
        condition1 = current_total > target_total
        condition2 = len(market_data.existing_sell_orders) > sell_count
        condition3 = len(market_data.existing_buy_orders) > buy_count

        logger.debug(f"撤单触发条件: 总订单超标={condition1}, 卖单超标={condition2}, 买单超标={condition3}")

        if condition1 or condition2 or condition3:
            logger.info("🔄 检测到订单超标，开始寻找远单...")

            # 找出所有不在理想价格集合中的现有订单（考虑价格容差）
            far_sell_orders = []
            far_buy_orders = []

            # 检查卖单
            for existing_price in market_data.existing_sell_orders:
                is_far = True
                for ideal_price in ideal_sell_prices:
                    if abs(existing_price - ideal_price) <= PRICE_TOLERANCE:
                        is_far = False
                        break
                if is_far:
                    far_sell_orders.append(existing_price)
                    logger.debug(f"    卖单为远单: ${existing_price:.2f}")

            # 检查买单
            for existing_price in market_data.existing_buy_orders:
                is_far = True
                for ideal_price in ideal_buy_prices:
                    if abs(existing_price - ideal_price) <= PRICE_TOLERANCE:
                        is_far = False
                        break
                if is_far:
                    far_buy_orders.append(existing_price)
                    logger.debug(f"    买单为远单: ${existing_price:.2f}")

            # 按照JS逻辑排序：卖单从高到低，买单从低到高
            far_sell_orders.sort(reverse=True)
            far_buy_orders.sort()

            logger.debug(f"远单统计: 卖单{len(far_sell_orders)}个, 买单{len(far_buy_orders)}个")
            if far_sell_orders:
                logger.debug(f"远卖单价: {[f'${p:.2f}' for p in far_sell_orders]}")
            if far_buy_orders:
                logger.debug(f"远买单价: {[f'${p:.2f}' for p in far_buy_orders]}")

            # 合并所有远单
            all_far = (
                    [{"type": "sell", "price": p} for p in far_sell_orders] +
                    [{"type": "buy", "price": p} for p in far_buy_orders]
            )

            # 按照JS逻辑：按距离中间价排序，优先撤销最远的（reverse=True表示从远到近）
            all_far.sort(key=lambda x: abs(x["price"] - mid_price), reverse=True)

            # 计算超额数量
            excess_orders = max(
                current_total - target_total,
                len(market_data.existing_sell_orders) - sell_count,
                len(market_data.existing_buy_orders) - buy_count,
                0
            )

            # JS限制最多撤销10个
            max_cancel = min(excess_orders, 10, len(all_far))

            logger.debug(f"超额数量: {excess_orders}, 最大撤销数: {max_cancel}")

            # 添加需要撤销的订单
            for i in range(max_cancel):
                if i < len(all_far):
                    order = all_far[i]
                    cancel_orders.append(order)
                    logger.debug(
                        f"    计划撤销: {order['type']}-${order['price']:.2f} (距离中间价: ${abs(order['price'] - mid_price):.2f})")
        else:
            logger.debug("订单数量未超标，无需寻找远单")

        # 记录日志
        logger.info(f"🎨 网格参数 | 窗口: ±${half_window:.0f} | 间距: ${interval} | 匹配容差: ${PRICE_TOLERANCE}")
        logger.info(f"📋 订单统计:")
        logger.info(
            f"  当前订单: {len(market_data.existing_sell_orders)}卖 + {len(market_data.existing_buy_orders)}买 = {current_total}")
        logger.info(f"  目标订单: {len(ideal_sell_prices)}卖 + {len(ideal_buy_prices)}买 = {target_total}")
        logger.info(f"  需下单: {len(new_sell_prices)}卖 + {len(new_buy_prices)}买")

        # 新增：显示详细的订单匹配信息
        if new_sell_prices:
            logger.info(f"  需要新增的卖单 ({len(new_sell_prices)}个):")
            for price in new_sell_prices[:10]:  # 最多显示10个
                # 检查这个价格是否已经有相近的订单（二次验证）
                has_nearby = any(abs(price - existing) <= PRICE_TOLERANCE
                                 for existing in market_data.existing_sell_orders)
                if has_nearby:
                    logger.warning(f"    ⚠️ ${price:.2f} - 可能有相近的订单存在！")
                else:
                    logger.info(f"    ✅ ${price:.2f}")
            if len(new_sell_prices) > 10:
                logger.info(f"    ... 还有{len(new_sell_prices) - 10}个")

        if new_buy_prices:
            logger.info(f"  需要新增的买单 ({len(new_buy_prices)}个):")
            for price in new_buy_prices[:10]:  # 最多显示10个
                # 检查这个价格是否已经有相近的订单（二次验证）
                has_nearby = any(abs(price - existing) <= PRICE_TOLERANCE
                                 for existing in market_data.existing_buy_orders)
                if has_nearby:
                    logger.warning(f"    ⚠️ ${price:.2f} - 可能有相近的订单存在！")
                else:
                    logger.info(f"    ✅ ${price:.2f}")
            if len(new_buy_prices) > 10:
                logger.info(f"    ... 还有{len(new_buy_prices) - 10}个")

        if cancel_orders:
            cancel_list = ", ".join([f"{o['type']}-${o['price']:.2f}" for o in cancel_orders[:5]])
            if len(cancel_orders) > 5:
                cancel_list += f" ... 等{len(cancel_orders)}单"
            logger.info(f"  需撤销: {cancel_list}")

            # 显示撤销原因
            if current_total > target_total:
                logger.info(f"    原因: 总订单数超标 ({current_total} > {target_total})")
            if len(market_data.existing_sell_orders) > sell_count:
                logger.info(f"    原因: 卖单数超标 ({len(market_data.existing_sell_orders)} > {sell_count})")
            if len(market_data.existing_buy_orders) > buy_count:
                logger.info(f"    原因: 买单数超标 ({len(market_data.existing_buy_orders)} > {buy_count})")
        else:
            logger.info("  无需撤销订单")

        return {
            "sell_prices": new_sell_prices,
            "buy_prices": new_buy_prices,
            "cancel_orders": cancel_orders,
            "market_data": market_data,
            "position_info": trade_info,
            "grid_info": {
                "mid_price": mid_price,
                "window_size": window_size,
                "half_window": half_window,
                "interval": interval,
                "sell_count": sell_count,
                "buy_count": buy_count,
                "price_tolerance": PRICE_TOLERANCE,
                "current_total": current_total,
                "target_total": target_total,
                "excess_orders": current_total - target_total if current_total > target_total else 0
            }
        }

    async def cancel_distant_orders(self, orders_to_cancel: List[Dict]):
        """撤销远单 - 修复ID格式问题和重复下单问题"""
        if not orders_to_cancel:
            return

        logger.info(f"🗑️  开始撤销 {len(orders_to_cancel)} 个远单...")

        # === 新增：获取当前价格，用于判断是否需要跳过撤单 ===
        try:
            ticker = self.trader.get_ticker(self.symbol)
            current_price = ticker.get('last', 0) if ticker else 0
            logger.debug(f"当前价格: ${current_price:.2f}")
        except Exception as e:
            logger.error(f"获取当前价格失败: {e}")
            current_price = 0

        # 获取当前所有挂单
        open_orders = self.get_open_orders()
        if not open_orders:
            logger.info("没有找到可撤销的挂单")
            return

        canceled_count = 0
        skipped_count = 0

        for target_order in orders_to_cancel:
            try:
                order_type = target_order['type']
                target_price = target_order['price']

                # # === 新增：检查是否需要跳过撤单（如果价格接近当前价格）===
                # if current_price > 0:
                #     cfg = GRID_STRATEGY_CONFIG
                #     #订单价格-限价
                #     price_diff = abs(target_price - current_price)
                #     #差价<=间距15(15/4)
                #     is_near_current_price = price_diff <= cfg["BASE_PRICE_INTERVAL"] * (cfg["MAX_MULTIPLIER"] // 4)
                #
                #     if is_near_current_price:
                #         logger.info(
                #             f"  ⏭️ 跳过撤单: {order_type}单 @ ${target_price:.2f} (距离当前价 ${price_diff:.1f}$，太近)")
                #         skipped_count += 1
                #         continue
                #
                # logger.info(f"  正在撤销{order_type}单 @ ${target_price:.2f}")

                # 查找匹配价格的订单（使用价格匹配）
                matched_order = None
                for open_order in open_orders:
                    # 使用价格和方向匹配（价格容差1美元）
                    if (open_order.get('side', '').lower() == order_type and
                            abs(open_order.get('price', 0) - target_price) < 1.0):
                        matched_order = open_order
                        break

                if matched_order:
                    # 关键修复：使用正确的client_order_id格式
                    client_order_id = matched_order.get('client_order_id')

                    # 如果client_order_id是十六进制格式，尝试从其他字段获取
                    if not client_order_id or '0x' in str(client_order_id):
                        # 尝试从metadata或raw_data中获取
                        if 'raw_data' in matched_order and matched_order['raw_data']:
                            metadata = matched_order['raw_data'].get('metadata', {})
                            client_order_id = metadata.get('client_order_id')

                        # 如果还是没有，使用order_id但转换为字符串
                        if not client_order_id:
                            client_order_id = str(matched_order.get('id', ''))

                    logger.debug(f"    使用client_order_id: {client_order_id}")

                    if client_order_id:
                        # 移除可能的0x前缀
                        if isinstance(client_order_id, str) and client_order_id.startswith('0x'):
                            client_order_id = client_order_id[2:]

                        success = self.trader.cancel_order(
                            client_order_id=client_order_id,
                            symbol=self.symbol
                        )
                        if success:
                            logger.info(f"    ✅ 成功撤销{order_type}单 @ ${target_price:.2f}")
                            canceled_count += 1
                        else:
                            logger.warning(f"    ⚠️  撤单请求失败，ID: {client_order_id}")
                    else:
                        logger.warning(f"    ⚠️  无法获取有效的client_order_id")

                    await asyncio.sleep(0.5)  # 避免请求过快
                else:
                    logger.info(f"    ℹ️  未找到匹配的{order_type}单 @ ${target_price:.2f}")

            except Exception as e:
                logger.error(f"    ❌ 撤销订单失败 @ ${target_order['price']:.2f}: {e}")

        logger.info(f"✅ 撤单完成，共撤销 {canceled_count}个，跳过 {skipped_count}个，计划 {len(orders_to_cancel)}个")

    async def place_new_orders(self, buy_prices: List[float], sell_prices: List[float]):
        """下新订单"""
        total_orders = len(buy_prices) + len(sell_prices)
        if total_orders == 0:
            logger.info("🔄 无需下新订单")
            return

        logger.info(f"📤 开始下 {total_orders} 个新订单...")

        # 下买单
        for price in buy_prices:
            try:
                client_order_id = self.trader.place_limit_order(
                    symbol=self.symbol,
                    side="buy",
                    quantity=self.order_size,
                    price=price
                )

                if client_order_id:
                    logger.info(f"  ✅ 限价买单已提交 @ ${price:.2f}")
                    self.active_orders[client_order_id] = {
                        "price": price,
                        "side": "buy",
                        "quantity": self.order_size,
                        "timestamp": time.time()
                    }
                    self.total_orders_placed += 1
                else:
                    logger.error(f"  ❌ 限价买单提交失败 @ ${price:.2f}")

                await asyncio.sleep(TRADING_CONFIG["ORDER_COOLDOWN"])

            except Exception as e:
                logger.error(f"  ❌ 下买单失败 @ ${price:.2f}: {e}")

        # 下卖单
        for price in sell_prices:
            try:
                client_order_id = self.trader.place_limit_order(
                    symbol=self.symbol,
                    side="sell",
                    quantity=self.order_size,
                    price=price
                )

                if client_order_id:
                    logger.info(f"  ✅ 限价卖单已提交 @ ${price:.2f}")
                    self.active_orders[client_order_id] = {
                        "price": price,
                        "side": "sell",
                        "quantity": self.order_size,
                        "timestamp": time.time()
                    }
                    self.total_orders_placed += 1
                else:
                    logger.error(f"  ❌ 限价卖单提交失败 @ ${price:.2f}")

                await asyncio.sleep(TRADING_CONFIG["ORDER_COOLDOWN"])

            except Exception as e:
                logger.error(f"  ❌ 下卖单失败 @ ${price:.2f}: {e}")

        logger.info(f"🎉 订单提交完成，共 {total_orders} 单")

    # ========== 风控管理 ==========

    async def trigger_risk_cooldown(self, reason: str):
        """触发风控冷却"""
        self.risk_cooling_down = True
        self.risk_triggered_reason = reason

        cooldown_minutes = TRADING_CONFIG["RISK_COOLDOWN_MINUTES"]
        self.risk_cool_down_end_time = time.time() + (cooldown_minutes * 60)

        end_time = datetime.fromtimestamp(self.risk_cool_down_end_time).strftime("%H:%M:%S")

        logger.warning(f"🚨 触发风控冷却: {reason}")
        logger.warning(f"⏰ 冷却时间: {cooldown_minutes}分钟，预计恢复时间: {end_time}")

        try:
            # 1. 平仓
            logger.info("🔄 执行风控平仓...")
            success = self.trader.close_position(self.symbol)
            if success:
                logger.info("  ✅ 平仓成功")
            else:
                logger.warning("  ⚠️  平仓失败或无持仓")

            await asyncio.sleep(1)

            # 2. 取消所有订单
            logger.info("🔄 取消所有挂单...")
            success = self.trader.cancel_all_orders(self.symbol)
            if success:
                logger.info("  ✅ 订单取消成功")
            else:
                logger.warning("  ⚠️  订单取消失败或无挂单")

            # 3. 清空活跃订单记录
            self.active_orders.clear()

            logger.info("✅ 风控处理完成，进入冷却期")

        except Exception as e:
            logger.error(f"❌ 风控处理失败: {e}")
            # 即使失败，也要保持冷却状态

    def check_risk_cooldown(self) -> bool:
        """检查风控冷却状态"""
        if not self.risk_cooling_down:
            return False

        current_time = time.time()
        if current_time >= self.risk_cool_down_end_time:
            # 冷却结束
            self.risk_cooling_down = False
            self.risk_triggered_reason = ""
            logger.info("✅ 风控冷却已结束，恢复交易")
            return False

        remaining = int(self.risk_cool_down_end_time - current_time)
        minutes = remaining // 60
        seconds = remaining % 60

        if minutes > 0:
            logger.info(f"⏳ 风控冷却中，剩余: {minutes}分{seconds}秒")
        else:
            logger.info(f"⏳ 风控冷却中，剩余: {seconds}秒")

        return True

    def reset_risk_cooldown(self):
        """手动重置风控冷却"""
        self.risk_cooling_down = False
        self.risk_cool_down_end_time = 0
        self.risk_triggered_reason = ""
        logger.info("✅ 风控冷却已手动重置")

    # ========== 辅助方法 ==========

    def update_performance_metrics(self):
        """更新性能指标"""
        runtime = time.time() - self.start_time
        hours = runtime / 3600

        # 获取当前仓位信息
        positions = self.trader.get_positions(self.symbol)
        position_info = ""

        if positions:
            for pos in positions:
                if pos['symbol'] == self.symbol:
                    side = "多" if pos['size'] > 0 else "空"
                    position_info = f"{side}仓 {abs(pos['size']):.4f} BTC @ ${pos['entry_price']:.2f}"
                    break

        logger.info(f"\n📈 性能统计:")
        logger.info(f"  运行时间: {hours:.1f}小时")
        logger.info(f"  循环次数: {self.cycle_count}")
        logger.info(f"  总下单数: {self.total_orders_placed}")
        logger.info(f"  活跃订单: {len(self.active_orders)}")
        logger.info(f"  订单大小: {self.order_size:.4f} BTC")
        if position_info:
            logger.info(f"  当前仓位: {position_info}")

    def get_status(self) -> Dict:
        """获取策略状态"""
        risk_status = {
            "in_cooldown": self.risk_cooling_down,
            "reason": self.risk_triggered_reason,
            "remaining_time": 0
        }

        if self.risk_cooling_down:
            remaining = int(self.risk_cool_down_end_time - time.time())
            risk_status["remaining_time"] = remaining
            risk_status["end_time"] = datetime.fromtimestamp(
                self.risk_cool_down_end_time
            ).strftime("%H:%M:%S")

        # 技术指标状态
        tech_status = {}
        if DATA_SOURCE_CONFIG.get("rsi_adx_enabled", False):
            tech_status = {
                "indicators_enabled": True,
                "last_rsi": self.last_indicators['rsi'] if self.last_indicators else None,
                "last_adx": self.last_indicators['adx'] if self.last_indicators else None,
                "market_condition": self.last_market_condition['market_condition']
                if self.last_market_condition else None,
                "trading_allowed": self.last_market_condition['trading_allowed']
                if self.last_market_condition else None,
            }
        else:
            tech_status = {"indicators_enabled": False}

        return {
            "running": True,
            "cycle_count": self.cycle_count,
            "active_orders": len(self.active_orders),
            "total_orders_placed": self.total_orders_placed,
            "order_size": self.order_size,
            "symbol": self.symbol,
            "start_time": datetime.fromtimestamp(self.start_time).strftime("%Y-%m-%d %H:%M:%S"),
            "runtime_hours": round((time.time() - self.start_time) / 3600, 1),
            "risk_cooldown": risk_status,
            "technical_analysis": tech_status,
        }

    def show_detailed_status(self):
        """显示详细状态信息"""
        status = self.get_status()

        print("\n" + "=" * 60)
        print("📊 网格交易策略 - 详细状态")
        print("=" * 60)

        print(f"📈 运行状态:")
        print(f"  运行时间: {status['runtime_hours']}小时")
        print(f"  循环次数: {status['cycle_count']}")
        print(f"  总下单数: {status['total_orders_placed']}")
        print(f"  活跃订单: {status['active_orders']}")
        print(f"  订单大小: {status['order_size']:.4f} BTC")
        print(f"  交易对: {status['symbol']}")

        print(f"\n🎯 技术指标:")
        if status['technical_analysis']['indicators_enabled']:
            print(f"  状态: 已启用")
            if status['technical_analysis']['last_rsi']:
                print(f"  最新RSI: {status['technical_analysis']['last_rsi']}")
                print(f"  最新ADX: {status['technical_analysis']['last_adx']}")
                print(f"  市场状况: {status['technical_analysis']['market_condition']}")
                print(f"  允许交易: {'是' if status['technical_analysis']['trading_allowed'] else '否'}")
        else:
            print(f"  状态: 已禁用")

        print(f"\n⚠️  风控状态:")
        if status['risk_cooldown']['in_cooldown']:
            remaining = status['risk_cooldown']['remaining_time']
            minutes = remaining // 60
            seconds = remaining % 60
            print(f"  状态: 冷却中")
            print(f"  原因: {status['risk_cooldown']['reason']}")
            print(f"  剩余时间: {minutes}分{seconds}秒")
            print(f"  恢复时间: {status['risk_cooldown']['end_time']}")
        else:
            print(f"  状态: 正常")

        print("=" * 60)
