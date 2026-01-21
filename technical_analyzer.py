#!/usr/bin/env python3
"""
技术指标分析器 - 计算RSI, ADX等指标
使用stockstats库进行技术分析[citation:8]
"""
import pandas as pd
import logging
from stockstats import StockDataFrame
from typing import Dict, Optional, Tuple
from config import INDICATOR_CONFIG

logger = logging.getLogger(__name__)


class TechnicalAnalyzer:
    def __init__(self):
        self.rsi_period = INDICATOR_CONFIG['rsi_period']
        self.adx_period = INDICATOR_CONFIG['adx_period']
        logger.info("技术指标分析器初始化完成")

    def calculate_indicators(self, df: pd.DataFrame) -> Optional[Dict]:
        """
        使用ta库计算RSI和ADX技术指标
        """
        if df is None or len(df) < max(self.rsi_period, self.adx_period) * 2:
            logger.error("数据不足，无法计算技术指标")
            return None

        try:
            # 确保数据是数值类型
            df_numeric = df[['Open', 'High', 'Low', 'Close', 'Volume']].apply(pd.to_numeric, errors='coerce')

            # 计算RSI
            from ta.momentum import RSIIndicator
            rsi_indicator = RSIIndicator(close=df_numeric['Close'], window=self.rsi_period)
            rsi_series = rsi_indicator.rsi()
            current_rsi = round(rsi_series.iloc[-1], 2) if not rsi_series.empty else 50.0

            # 计算ADX (需要High, Low, Close)
            from ta.trend import ADXIndicator
            adx_indicator = ADXIndicator(high=df_numeric['High'],
                                         low=df_numeric['Low'],
                                         close=df_numeric['Close'],
                                         window=self.adx_period)
            adx_series = adx_indicator.adx()
            current_adx = round(adx_series.iloc[-1], 2) if not adx_series.empty else 25.0

            # 获取最新价格
            current_close = float(df_numeric['Close'].iloc[-1]) if not df_numeric['Close'].empty else 0.0

            indicators = {
                'rsi': current_rsi,
                'adx': current_adx,
                'price': current_close,
                'timestamp': df['Timestamp'].iloc[-1] if 'Timestamp' in df.columns else pd.Timestamp.now(),
                'rsi_series': rsi_series.tolist()[-20:],  # 最近20个值
                'adx_series': adx_series.tolist()[-20:],  # 最近20个值
            }

            logger.info(f"✅ 指标计算完成: RSI={current_rsi}, ADX={current_adx}, Price={current_close}")
            return indicators

        except Exception as e:
            logger.error(f"❌ 计算技术指标失败 (ta库): {e}", exc_info=True)
            return None

    def evaluate_market_condition(self, indicators: Dict) -> Dict:
        """
        根据RSI和ADX指标评估市场状况
        返回评估结果和交易建议
        """
        if not indicators:
            return {'error': '无有效指标数据'}

        rsi = indicators['rsi']
        adx = indicators['adx']

        # 从配置中获取阈值
        rsi_oversold = INDICATOR_CONFIG['rsi_oversold']
        rsi_overbought = INDICATOR_CONFIG['rsi_overbought']
        adx_trend_threshold = INDICATOR_CONFIG['adx_trend_threshold']
        adx_strong_trend = INDICATOR_CONFIG['adx_strong_trend']

        result = {
            'rsi': rsi,
            'adx': adx,
            'rsi_status': '',
            'adx_status': '',
            'market_condition': '',
            'trading_allowed': True,
            'reason': ''
        }

        # 1. 评估ADX趋势强度[citation:8]
        if adx > adx_strong_trend:
            result['adx_status'] = '强趋势'
            result['market_condition'] = '强趋势市场'
            result['trading_allowed'] = False
            result['reason'] = f'ADX({adx}) > {adx_strong_trend}，市场处于强趋势，不适合网格交易'

        elif adx > adx_trend_threshold:
            result['adx_status'] = '中等趋势'
            result['market_condition'] = '趋势市场'
            # 趋势市场中需要更严格的RSI检查
            rsi_tolerance = 5  # 收紧容忍度

            if rsi < (rsi_oversold - rsi_tolerance) or rsi > (rsi_overbought + rsi_tolerance):
                result['trading_allowed'] = False
                result['reason'] = f'趋势市场中RSI({rsi})过于极端'
            else:
                result['trading_allowed'] = True
                result['reason'] = '趋势市场但RSI在可控范围内，谨慎交易'

        else:
            result['adx_status'] = '震荡'
            result['market_condition'] = '震荡市场'

            # 2. 评估RSI超买超卖[citation:8]
            if rsi < rsi_oversold:
                result['rsi_status'] = '超卖'
            elif rsi > rsi_overbought:
                result['rsi_status'] = '超买'
            else:
                result['rsi_status'] = '中性'

            # 震荡市场最适合网格交易
            if rsi_oversold <= rsi <= rsi_overbought:
                result['trading_allowed'] = True
                result['reason'] = '震荡市场且RSI在合理区间，适合网格交易'
            else:
                result['trading_allowed'] = False
                result['reason'] = f'震荡市场但RSI({rsi})不在{rsi_oversold}-{rsi_overbought}区间'

        return result