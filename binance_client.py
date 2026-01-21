#!/usr/bin/env python3
"""
币安API客户端 - 用于获取市场K线数据
"""
import ccxt
import pandas as pd
import logging
from typing import Optional, Dict, List
from config import BINANCE_CONFIG

logger = logging.getLogger(__name__)


class BinanceClient:
    def __init__(self):
        self.symbol = BINANCE_CONFIG['symbol']
        self.timeframe = BINANCE_CONFIG['timeframe']

        # 使用ccxt库初始化币安连接[citation:1]
        self.exchange = ccxt.binance({
            'apiKey': BINANCE_CONFIG['api_key'],
            'secret': BINANCE_CONFIG['api_secret'],
            'timeout': 30000,
            'enableRateLimit': BINANCE_CONFIG['enableRateLimit'],
            'options': BINANCE_CONFIG['options']
        })

        # 加载市场数据
        try:
            self.exchange.load_markets()
            logger.info(f"✅ 币安客户端初始化成功，交易对: {self.symbol}")
        except Exception as e:
            logger.error(f"❌ 币安客户端初始化失败: {e}")
            raise

    def fetch_ohlcv(self, limit: int = None) -> Optional[pd.DataFrame]:
        """
        获取OHLCV（K线）数据[citation:1]
        返回包含 ['Timestamp', 'Open', 'High', 'Low', 'Close', 'Volume'] 的DataFrame
        """
        try:
            if limit is None:
                limit = BINANCE_CONFIG['ohlcv_limit']

            logger.debug(f"获取{self.symbol}的{limit}条{self.timeframe}K线数据...")

            # 调用ccxt的fetch_ohlcv方法[citation:1]
            ohlcv = self.exchange.fetch_ohlcv(
                symbol=self.symbol,
                timeframe=self.timeframe,
                limit=limit
            )

            # 转换为Pandas DataFrame[citation:1]
            df = pd.DataFrame(
                ohlcv,
                columns=['Timestamp', 'Open', 'High', 'Low', 'Close', 'Volume']
            )

            # 转换数据类型
            df[['Open', 'High', 'Low', 'Close', 'Volume']] = df[
                ['Open', 'High', 'Low', 'Close', 'Volume']
            ].astype(float)

            # 转换时间戳为可读格式（可选）
            df['Timestamp'] = pd.to_datetime(df['Timestamp'], unit='ms')

            logger.info(f"✅ 成功获取{len(df)}条K线数据，最新时间: {df['Timestamp'].iloc[-1]}")
            return df

        except Exception as e:
            logger.error(f"❌ 获取K线数据失败: {e}")
            return None

    def get_current_price(self) -> Optional[float]:
        """获取当前最新价格"""
        try:
            ticker = self.exchange.fetch_ticker(self.symbol)
            return float(ticker['last'])
        except Exception as e:
            logger.error(f"获取当前价格失败: {e}")
            return None