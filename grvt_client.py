#!/usr/bin/env python3
"""
GRVT 交易客户端 (简化增强版)
专注于稳定连接、精准下单和可靠的仓位查询。
"""
import os
import sys
import time
import json
import logging
from typing import Optional, Dict, List

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class GrvtTrader:
    def __init__(self, api_key: str, private_key: str, trading_account_id: str, env: str = "testnet"):
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        pysdk_path = os.path.join(project_root, 'exchange', 'exchange_grvt', 'src')

        if pysdk_path not in sys.path:
            sys.path.insert(0, pysdk_path)

        try:
            from pysdk.grvt_ccxt import GrvtCcxt
            from pysdk.grvt_ccxt_env import GrvtEnv

            env_map = {"prod": GrvtEnv.PROD, "testnet": GrvtEnv.TESTNET, "staging": GrvtEnv.STAGING, "dev": GrvtEnv.DEV}
            grvt_env = env_map.get(env.lower(), GrvtEnv.TESTNET)

            parameters = {"api_key": api_key, "trading_account_id": trading_account_id, "private_key": private_key}

            logger.info(f"初始化 GRVT 客户端 ({env}环境)")
            self.client = GrvtCcxt(env=grvt_env, parameters=parameters)

            logger.info("✅ 客户端初始化成功")
        except ImportError as e:
            logger.error(f"❌ 无法导入 GRVT SDK: {e}")
            raise
        except Exception as e:
            logger.error(f"❌ 客户端初始化失败: {e}")
            raise

    # 价格与订单簿
    def get_ticker(self, symbol: str) -> Optional[Dict]:
        """
        获取单个交易对的 ticker 数据
        已修正：正确处理GRVT API返回的嵌套数据结构 {'result': {...}}
        """
        try:
            # 1. 调用底层API获取原始数据
            ticker_data = self.client.fetch_ticker(symbol)

            # 2. 调试：打印原始响应结构（调试完成后可注释掉）
            # 这将帮助你确认API返回的确切格式
            logger.debug(f"[DEBUG] fetch_ticker 原始响应类型: {type(ticker_data)}")

            # 3. 核心修复：处理响应可能是字典且包含'result'键的情况
            if isinstance(ticker_data, dict):
                # GRVT API 返回的数据通常在 'result' 字段中
                if 'result' in ticker_data and isinstance(ticker_data['result'], dict):
                    result_data = ticker_data['result']
                    logger.debug(f"[DEBUG] 找到嵌套的 'result' 字段")
                else:
                    # 如果没有'result'键，则直接使用整个字典
                    result_data = ticker_data
                    logger.debug(f"[DEBUG] 未找到嵌套的 'result' 字段，使用原始字典")
            elif isinstance(ticker_data, list):
                logger.warning(f"响应为列表，尝试解析: {ticker_data[:3] if len(ticker_data) > 3 else ticker_data}...")
                # 简单处理：如果列表第一个元素是字典
                if len(ticker_data) > 0 and isinstance(ticker_data[0], dict):
                    result_data = ticker_data[0]
                else:
                    logger.error(f"无法解析的列表响应结构")
                    return None
            else:
                logger.error(f"无法处理的响应类型: {type(ticker_data)}")
                return None

            # 4. 从解析后的数据字典中提取价格字段（关键步骤）
            # GRVT API 使用的字段名是 'best_bid_price' 和 'best_ask_price'
            # 我们提供多种可能的键名以增强兼容性
            last_price = result_data.get('last_price') or result_data.get('last') or result_data.get('price') or 0
            bid_price = result_data.get('best_bid_price') or result_data.get('bid') or result_data.get('bidPrice') or 0
            ask_price = result_data.get('best_ask_price') or result_data.get('ask') or result_data.get('askPrice') or 0

            # 5. 将价格安全地转换为浮点数
            try:
                last_price = float(last_price) if last_price not in [None, '', 0] else 0.0
                bid_price = float(bid_price) if bid_price not in [None, '', 0] else 0.0
                ask_price = float(ask_price) if ask_price not in [None, '', 0] else 0.0
            except (ValueError, TypeError) as e:
                logger.error(
                    f"价格字段转换失败: {e}。原始数据 - last: '{last_price}', bid: '{bid_price}', ask: '{ask_price}'")
                # 即使转换失败，也返回0值，避免整个策略崩溃
                last_price, bid_price, ask_price = 0.0, 0.0, 0.0

            # 6. 记录解析结果用于验证
            logger.debug(f"[DEBUG] 解析出的价格 -> last: {last_price}, bid: {bid_price}, ask: {ask_price}")

            # 7. 构建并返回标准格式的ticker字典
            return {
                'symbol': symbol,
                'last': last_price,
                'bid': bid_price,
                'ask': ask_price,
                'timestamp': int(time.time() * 1000),  # 使用当前时间戳
                # 可选：包含一些原始数据用于高级调试
                'raw_last_price': result_data.get('last_price'),
                'raw_bid_price': result_data.get('best_bid_price'),
                'raw_ask_price': result_data.get('best_ask_price'),
            }

        except Exception as e:
            logger.error(f"获取 {symbol} ticker 数据失败: {e}", exc_info=True)
            return None

    def _get_ticker_fallback(self, symbol: str) -> Optional[Dict]:
        """备用方法：尝试不同的方式获取价格"""
        try:
            # 方法1：尝试使用 fetch_tickers 获取所有，然后筛选
            all_tickers = self.client.fetch_tickers()
            if symbol in all_tickers:
                ticker = all_tickers[symbol]
                return {
                    'symbol': symbol,
                    'last': float(ticker.get('last', 0)),
                    'bid': float(ticker.get('bid', 0)),
                    'ask': float(ticker.get('ask', 0)),
                    'timestamp': int(time.time() * 1000),
                }

            # 方法2：尝试不同的 symbol 格式
            symbol_variants = [
                symbol,
                symbol.replace('-', '/'),
                symbol.replace('PERP', 'USDT'),  # BTC-USDT 格式
            ]

            for sym in symbol_variants:
                try:
                    ticker = self.client.fetch_ticker(sym)
                    if ticker:
                        return {
                            'symbol': symbol,
                            'last': float(ticker.get('last', 0)),
                            'bid': float(ticker.get('bid', 0)),
                            'ask': float(ticker.get('ask', 0)),
                            'timestamp': int(time.time() * 1000),
                        }
                except:
                    continue

        except Exception as e:
            logger.error(f"备用方法获取价格也失败: {e}")

        return None

    def _parse_ticker_from_list(self, data_list: list, symbol: str) -> Optional[Dict]:
        """从列表响应中解析 ticker 数据（备用方法）"""
        try:
            # 这里根据实际的API响应格式调整
            # 假设列表格式为 [last_price, bid_price, ask_price, ...]
            if len(data_list) >= 3:
                return {
                    'symbol': symbol,
                    'last': float(data_list[0]) if data_list[0] else 0,
                    'bid': float(data_list[1]) if data_list[1] else 0,
                    'ask': float(data_list[2]) if data_list[2] else 0,
                    'timestamp': int(time.time() * 1000),
                }
        except Exception as e:
            logger.error(f"从列表解析 ticker 失败: {e}")

        return None

    def get_bid2_price(self, symbol: str) -> Optional[float]:
        """获取第二档买价（修正版）"""
        try:
            # 先尝试获取完整的深度数据
            orderbook = self.client.fetch_order_book(symbol, limit=5)
            if orderbook and 'bids' in orderbook and len(orderbook['bids']) >= 2:
                # 第二档买价是 bids[1]
                bid2_price = float(orderbook['bids'][1][0])
                # 调整到最小价格变动单位
                return self.adjust_price_to_tick(bid2_price)

            # 如果获取深度失败，回退到原来的逻辑
            ticker = self.get_ticker(symbol)
            if ticker and ticker['bid'] > 0:
                return self.adjust_price_to_tick(ticker['bid'] - 0.1)

            return None
        except Exception as e:
            logger.error(f"获取第二档买价失败: {e}")
            return None

    # 核心交易功能
    def place_limit_order(self, symbol: str, side: str, quantity: float, price: float) -> Optional[str]:
        """
        下限价挂单 - 修正版 (使用已验证的位置参数调用)
        严格遵循项目内SDK的调用规范。
        """
        try:
            from pysdk.grvt_ccxt_types import GrvtOrderSide

            # 1. 参数验证与调整
            if price <= 0:
                raise ValueError(f"限价单价格必须大于0，收到: {price}")

            adjusted_price = self.adjust_price_to_tick(price)
            # 确保数量格式正确（字符串）
            quantity_str = f"{quantity:.6f}".rstrip('0').rstrip('.')

            # 2. 转换订单方向 (与GrvtAdapter完全一致)
            grvt_side: GrvtOrderSide = "buy" if side.lower() in ["buy", "long"] else "sell"

            # 3. 准备参数 (与GrvtAdapter完全一致)
            params = {"reduce_only": False}

            logger.info(f"挂限价单: {side.upper()} {quantity} {symbol} @ {adjusted_price}")

            # 4. 关键修正：使用位置参数调用，不添加关键字
            # 这是根据您之前成功的 GrvtAdapter 代码确定的调用方式
            result = self.client.create_limit_order(
                symbol,  # 参数1: 交易对
                grvt_side,  # 参数2: 方向
                quantity_str,  # 参数3: 数量 (字符串)
                str(adjusted_price),  # 参数4: 价格 (字符串)
                params  # 参数5: 参数字典
            )

            # 5. 结果处理
            if result and isinstance(result, dict):
                # 从 metadata 中提取 client_order_id (与GrvtAdapter逻辑一致)
                metadata = result.get("metadata", {})
                client_order_id = metadata.get("client_order_id")

                if client_order_id:
                    logger.info(f"✅ 限价单挂单成功，订单ID: {client_order_id}")
                    # 可选：记录完整结果用于调试
                    logger.debug(f"完整订单返回: {result}")
                    return client_order_id
                else:
                    # 尝试从其他可能的位置查找
                    if "result" in result:
                        alt_id = result["result"].get("client_order_id")
                        if alt_id:
                            logger.info(f"✅ 限价单挂单成功 (从result字段)，订单ID: {alt_id}")
                            return alt_id

                    logger.warning(f"挂单成功但未找到订单ID。返回结构: {result}")
                    # 即使没有ID，如果result不为空，也许可以认为请求成功？（根据SDK行为调整）
                    # 暂时返回None，触发重试逻辑更安全
                    return None
            else:
                logger.error(f"挂单失败: SDK返回空或非字典结果。")
                return None

        except Exception as e:
            logger.error(f"挂限价单失败: {e}", exc_info=True)
            return None

    def cancel_order(self, client_order_id: str, symbol: str = None) -> bool:
        """
        取消订单 - 修复响应处理
        """
        try:
            if not client_order_id:
                logger.error("cancel_order: client_order_id 为空")
                return False

            # 清理client_order_id
            if isinstance(client_order_id, str):
                # 移除可能的0x前缀
                if client_order_id.startswith('0x'):
                    client_order_id = client_order_id[2:]
                # 移除可能的空格
                client_order_id = client_order_id.strip()

            logger.debug(f"取消订单: client_order_id={client_order_id}, symbol={symbol or self.symbol}")

            # 构建参数
            params = {"client_order_id": client_order_id}

            # 调用API取消订单
            result = self.client.cancel_order(id=None, symbol=symbol, params=params)

            # ===== 关键修复：正确处理多种可能的响应格式 =====

            # 情况1：API返回None或空值
            if result is None:
                logger.warning(f"cancel_order: API返回None，client_order_id={client_order_id}")
                return False

            # 情况2：API返回布尔值
            if isinstance(result, bool):
                if result:
                    logger.info(f"✅ 撤单成功 (布尔值): {client_order_id}")
                else:
                    logger.warning(f"撤单失败 (布尔值): {client_order_id}")
                return result

            # 情况3：API返回字典
            if isinstance(result, dict):
                # 格式1: {'result': {'ack': True}}
                if 'result' in result:
                    result_data = result['result']
                    if isinstance(result_data, dict) and result_data.get('ack', False):
                        logger.info(f"✅ 撤单成功 (result.ack): {client_order_id}")
                        return True
                    elif isinstance(result_data, bool) and result_data:
                        logger.info(f"✅ 撤单成功 (result布尔值): {client_order_id}")
                        return True

                # 格式2: {'success': True, ...}
                if result.get('success', False):
                    logger.info(f"✅ 撤单成功 (success字段): {client_order_id}")
                    return True

                # 格式3: 直接包含'ack'字段
                if result.get('ack', False):
                    logger.info(f"✅ 撤单成功 (ack字段): {client_order_id}")
                    return True

                # 格式4: 包含'message'或'status'字段表示成功
                if 'message' in result and 'success' in result['message'].lower():
                    logger.info(f"✅ 撤单成功 (消息字段): {client_order_id}")
                    return True

                # 如果以上都不匹配，但字典不为空，尝试检查其他可能的成功标志
                if result:
                    logger.warning(f"撤单响应无法识别: {result}")
                    # 如果响应中有数据但没有明确的成功标志，我们可以认为请求已发送
                    # 但为了安全，返回False并记录警告
                    return False
                else:
                    logger.warning(f"撤单返回空字典")
                    return False

            # 情况4：API返回字符串
            if isinstance(result, str):
                if 'success' in result.lower() or 'ack' in result.lower():
                    logger.info(f"✅ 撤单成功 (字符串): {client_order_id}")
                    return True
                else:
                    logger.warning(f"撤单返回无法识别的字符串: {result}")
                    return False

            # 情况5：其他类型
            logger.warning(f"撤单返回未知类型: {type(result)}")
            return False

        except Exception as e:
            logger.error(f"撤单异常失败: client_order_id={client_order_id}, 错误: {e}", exc_info=True)
            return False

    def cancel_order_by_price(self, symbol: str, side: str, price: float) -> bool:
        """
        通过价格和方向取消订单
        """
        try:
            # 获取所有挂单
            open_orders = self.get_open_orders()

            for order in open_orders:
                order_side = order.get('side', '').lower()
                order_price = order.get('price', 0)

                # 使用容差匹配
                PRICE_TOLERANCE = 0.5

                if (order_side == side.lower() and
                        abs(order_price - price) <= PRICE_TOLERANCE):

                    client_order_id = order.get('client_order_id')
                    if client_order_id:
                        return self.cancel_order(client_order_id, symbol)

            logger.info(f"未找到匹配的订单: {side} @ ${price:.2f}")
            return False

        except Exception as e:
            logger.error(f"通过价格撤单失败: {e}")
            return False

    def cancel_all_orders(self, symbol: str = None) -> bool:
        """取消所有订单"""
        try:
            params = {"kind": "PERPETUAL"}
            # 假设 self.client.cancel_all_orders 返回布尔值
            result = self.client.cancel_all_orders(params=params)

            # 直接处理布尔值结果
            if result:
                logger.info(f"✅ 全部撤单成功")
            else:
                logger.warning(f"⚠️ 撤单返回失败")

            return result  # 直接返回API的布尔结果

        except Exception as e:
            logger.error(f"全部撤单失败: {e}")
            return False

    # 仓位管理 (关键)
    def get_positions(self, symbol: str = None) -> List[Dict]:
        try:
            symbols = [symbol] if symbol else []
            positions_data = self.client.fetch_positions(symbols=symbols)
            positions = []
            for pos in positions_data:
                size = float(pos.get("size", 0))
                if abs(size) > 0.0001:
                    positions.append({
                        'symbol': pos.get("instrument", ""),
                        'size': size,
                        'side': "long" if size > 0 else "short",
                        'entry_price': float(pos.get("entry_price", 0)),
                        'mark_price': float(pos.get("mark_price", 0)),
                    })
            return positions
        except Exception as e:
            logger.error(f"获取持仓失败: {e}")
            return []

    def get_net_position(self, symbol: str) -> float:
        positions = self.get_positions(symbol)
        net = sum(p['size'] for p in positions)
        return round(net, 4)

    def close_position(self, symbol: str) -> bool:
        try:
            positions = self.get_positions(symbol)
            for pos in positions:
                size = pos['size']
                if abs(size) > 0.0001:
                    close_side = "sell" if size > 0 else "buy"
                    qty_str = f"{abs(size):.6f}".rstrip('0').rstrip('.')
                    logger.info(f"市价平仓: {close_side.upper()} {abs(size)} {symbol}")
                    params = {"reduce_only": True}
                    result = self.client.create_order(symbol, "market", close_side, qty_str, None, params)
                    if result:
                        logger.info("✅ 平仓指令发送成功")
                        return True
            logger.info("没有持仓需要平仓")
            return True
        except Exception as e:
            logger.error(f"平仓失败: {e}")
            return False

    # 订单状态
    def check_order_status(self, client_order_id: str) -> Optional[Dict]:
        try:
            params = {"client_order_id": client_order_id}
            order_data = self.client.fetch_order(id=None, params=params)
            if not order_data or "result" not in order_data:
                return None
            result = order_data["result"]
            legs = result.get("legs", [])
            if not legs:
                return None
            leg = legs[0]
            metadata = result.get("metadata", {})
            status = result.get("status", "UNKNOWN").lower()
            return {
                'order_id': client_order_id,
                'side': "buy" if leg.get("is_buying_asset") else "sell",
                'price': float(leg.get("limit_price", 0)),
                'quantity': float(leg.get("size", 0)),
                'filled_qty': float(leg.get("filled_size", 0)),
                'status': status,
                'is_filled': status in ["filled", "closed"],
                'is_open': status in ["open", "partially_filled"],
            }
        except Exception as e:
            logger.error(f"查询订单状态失败: {e}")
            return None

    # ========== 新增：get_open_orders方法 ==========
    def get_open_orders(self, symbol: str = None) -> List[Dict]:
        """
        获取当前所有挂单 - 关键修复！
        根据fetch_open_orders的实际返回格式解析
        """
        try:
            open_orders = []

            # 调用GRVT SDK获取订单
            orders_data = self.client.fetch_open_orders(symbol=symbol)

            logger.debug(f"fetch_open_orders返回类型: {type(orders_data)}")

            # 情况1：返回的是字典，包含'result'字段
            if isinstance(orders_data, dict):
                if 'result' in orders_data:
                    result_data = orders_data['result']
                    logger.debug(f"找到'result'字段，类型: {type(result_data)}")

                    if isinstance(result_data, list):
                        orders_list = result_data
                        logger.info(f"从result字段获取到 {len(orders_list)} 个订单")
                    elif isinstance(result_data, dict):
                        if 'orders' in result_data and isinstance(result_data['orders'], list):
                            orders_list = result_data['orders']
                            logger.info(f"从result.orders字段获取到 {len(orders_list)} 个订单")
                        else:
                            logger.warning(
                                f"result字段格式无法识别: {result_data.keys() if isinstance(result_data, dict) else result_data}")
                            return []
                    else:
                        logger.warning(f"result字段类型无法识别: {type(result_data)}")
                        return []
                else:
                    logger.warning("fetch_open_orders返回字典但没有result字段")
                    return []

            # 情况2：直接返回列表
            elif isinstance(orders_data, list):
                logger.info(f"fetch_open_orders直接返回 {len(orders_data)} 个订单")
                orders_list = orders_data

            else:
                logger.warning(f"fetch_open_orders返回未知类型: {type(orders_data)}")
                return []

            # 解析订单列表
            for idx, order in enumerate(orders_list):
                try:
                    # ===== 关键修复：从legs字段提取价格和方向 =====
                    price = 0.0
                    side = 'unknown'
                    quantity = 0.0
                    filled_qty = 0.0

                    # 检查是否有legs字段
                    if 'legs' in order and isinstance(order['legs'], list) and len(order['legs']) > 0:
                        leg = order['legs'][0]  # 通常第一个leg包含主要信息

                        # 从leg中提取价格
                        if 'limit_price' in leg:
                            price_str = leg['limit_price']
                        elif 'price' in leg:
                            price_str = leg['price']
                        else:
                            price_str = '0'

                        # 转换价格
                        try:
                            if isinstance(price_str, str):
                                price_clean = ''.join(c for c in price_str if c.isdigit() or c in '.-')
                                price = float(price_clean) if price_clean else 0.0
                            else:
                                price = float(price_str)
                        except (ValueError, TypeError) as e:
                            logger.warning(f"订单{idx}: 价格转换失败 '{price_str}': {e}")
                            price = 0.0

                        # 从leg中提取方向
                        if 'is_buying_asset' in leg:
                            is_buying = leg['is_buying_asset']
                            side = 'buy' if is_buying else 'sell'
                        elif 'side' in leg:
                            side = leg['side'].lower()

                        # 从leg中提取数量
                        if 'size' in leg:
                            try:
                                quantity = float(leg['size'])
                            except (ValueError, TypeError):
                                quantity = 0.0

                        # 从leg中提取已成交数量
                        if 'filled_size' in leg:
                            try:
                                filled_qty = float(leg['filled_size'])
                            except (ValueError, TypeError):
                                filled_qty = 0.0
                    else:
                        logger.warning(f"订单{idx}没有legs字段或legs为空")

                    # 提取状态
                    status = 'unknown'
                    if 'state' in order:
                        state = order['state']
                        if isinstance(state, str):
                            status = state.lower()
                        elif isinstance(state, int):
                            status_map = {1: 'open', 2: 'filled', 3: 'cancelled', 4: 'expired'}
                            status = status_map.get(state, 'unknown')
                    elif 'status' in order:
                        status = order['status'].lower()

                    # 如果状态还是unknown，但有价格和数量，默认为open
                    if status == 'unknown' and price > 0 and quantity > 0:
                        status = 'open'

                    # 只处理活跃订单
                    if status not in ['open', 'partially_filled']:
                        logger.debug(f"订单{idx}: 状态为{status}，不是活跃挂单，跳过")
                        continue

                    # 检查是否为有效的限价单（价格>0，数量>0）
                    if price <= 0 or quantity <= 0:
                        logger.debug(f"订单{idx}: 价格({price})或数量({quantity})无效，跳过")
                        continue

                    # 提取订单ID
                    order_id = (
                            order.get('client_order_id') or
                            order.get('order_id') or
                            order.get('id') or
                            f"unknown_{idx}"
                    )

                    # 构建订单信息
                    order_info = {
                        'id': order_id,
                        'client_order_id': order_id,
                        'symbol': order.get('symbol', symbol or 'BTC_USDT_Perp'),
                        'side': side,
                        'price': price,
                        'quantity': quantity,
                        'filled': filled_qty,
                        'remaining': max(0.0, quantity - filled_qty),
                        'status': status,
                        'timestamp': order.get('timestamp', int(time.time() * 1000)),
                        'raw_data': order  # 保留原始数据用于调试
                    }

                    # 记录解析的订单信息
                    logger.debug(f"解析订单{idx}: {side} @ ${price:.2f}, 数量: {quantity}, 状态: {status}")

                    open_orders.append(order_info)

                except Exception as e:
                    logger.error(f"解析订单{idx}失败: {e}", exc_info=True)
                    continue

            logger.info(f"✅ 成功解析 {len(open_orders)} 个有效挂单")

            # 按价格排序并打印
            if open_orders:
                sell_orders = [o for o in open_orders if o['side'] == 'sell']
                buy_orders = [o for o in open_orders if o['side'] == 'buy']

                logger.info(f"卖单: {len(sell_orders)}个")
                if sell_orders:
                    sell_prices = [o['price'] for o in sell_orders]
                    logger.info(f"  价格范围: ${min(sell_prices):.2f} ~ ${max(sell_prices):.2f}")
                    logger.info(f"  前5个价格: {[f'${p:.2f}' for p in sorted(sell_prices)[:5]]}")

                logger.info(f"买单: {len(buy_orders)}个")
                if buy_orders:
                    buy_prices = [o['price'] for o in buy_orders]
                    logger.info(f"  价格范围: ${min(buy_prices):.2f} ~ ${max(buy_prices):.2f}")
                    logger.info(f"  前5个价格: {[f'${p:.2f}' for p in sorted(buy_prices, reverse=True)[:5]]}")

            return open_orders

        except Exception as e:
            logger.error(f"获取挂单失败: {e}", exc_info=True)
            return []

    # 工具函数
    def adjust_price_to_tick(self, price: float, tick_size: float = 0.05) -> float:
        adjusted = round(price / tick_size) * tick_size
        return round(adjusted, 2)