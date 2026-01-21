#!/usr/bin/env python3
"""
GRVT BTC网格交易主程序
"""
import time
import signal
import logging
import asyncio
import sys
from typing import Optional

from grvt_client import GrvtTrader
from strategy import GridStrategy
from config import *

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('grid_trading.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class GridTradingBot:
    """网格交易机器人"""

    def __init__(self):
        self.trader: Optional[GrvtTrader] = None
        self.strategy: Optional[GridStrategy] = None
        self.running = False
        self.loop = None

        # 设置信号处理
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

        logger.info("网格交易机器人初始化...")

    def signal_handler(self, signum, frame):
        """处理退出信号"""
        logger.info(f"收到退出信号 {signum}")
        self.stop()

    def initialize(self) -> bool:
        """初始化交易客户端和策略"""
        try:
            logger.info("初始化GRVT交易客户端...")

            # 初始化交易客户端
            self.trader = GrvtTrader(
                api_key=GRVT_CONFIG["api_key"],
                private_key=GRVT_CONFIG["private_key"],
                trading_account_id=GRVT_CONFIG["trading_account_id"],
                env=GRVT_CONFIG["env"]
            )

            # 测试连接
            ticker = self.trader.get_ticker(GRVT_CONFIG["symbol"])
            if not ticker:
                logger.error("无法获取价格数据，请检查连接")
                return False

            logger.info(f"连接成功！当前价格: ${ticker['last']:.2f}")

            # 初始化策略（策略会从TRADING_CONFIG读取ORDER_SIZE）
            self.strategy = GridStrategy(self.trader)

            # ❌ 删除这行，策略已经从配置读取了订单大小
            # order_size = 0.001
            # self.strategy.set_order_size(order_size)

            logger.info("✅ 初始化完成")
            return True

        except Exception as e:
            logger.error(f"初始化失败: {e}", exc_info=True)
            return False

    async def run(self):
        """运行主循环"""
        if not self.initialize():
            logger.error("初始化失败，程序退出")
            return

        self.running = True
        logger.info("🚀 网格交易机器人启动")

        try:
            while self.running:
                start_time = time.time()

                # 执行网格循环
                await self.strategy.execute_grid_cycle()

                # 计算执行时间
                execution_time = time.time() - start_time

                # 根据状态确定等待时间
                if self.strategy.risk_cooling_down:
                    interval = TRADING_CONFIG["CHECK_INTERVAL_RISK"]
                else:
                    interval = TRADING_CONFIG["MONITOR_INTERVAL"]

                # 调整等待时间
                wait_time = max(interval - execution_time, 1)

                # 每10个周期显示状态
                if self.strategy.cycle_count % 10 == 0:
                    self.show_status()

                # 等待下一次循环
                await asyncio.sleep(wait_time)

        except Exception as e:
            logger.error(f"主循环异常: {e}", exc_info=True)
        finally:
            self.cleanup()

    def show_status(self):
        """显示当前状态"""
        if not self.strategy:
            return

        status = self.strategy.get_status()

        logger.info("\n" + "=" * 50)
        logger.info("📊 网格交易状态")
        logger.info("=" * 50)
        logger.info(f"运行时间: {status['start_time']}")
        logger.info(f"循环次数: {status['cycle_count']}")
        logger.info(f"活跃订单: {status['active_orders']}")
        logger.info(f"订单大小: {status['order_size']} BTC")
        logger.info(f"交易对: {status['symbol']}")

        if status['risk_cooldown']['in_cooldown']:
            remaining = status['risk_cooldown']['remaining_time']
            minutes = remaining // 60
            seconds = remaining % 60
            logger.warning(f"⚠️ 风控冷却中 - {status['risk_cooldown']['reason']}")
            logger.warning(f"剩余时间: {minutes}分{seconds}秒")
        else:
            logger.info("✅ 交易正常")

        logger.info("=" * 50)

    def stop(self):
        """停止机器人"""
        logger.info("正在停止网格交易机器人...")
        self.running = False

        if self.strategy:
            # 执行清理操作
            try:
                logger.info("取消所有挂单...")
                self.trader.cancel_all_orders(GRVT_CONFIG["symbol"])

                logger.info("平仓...")
                self.trader.close_position(GRVT_CONFIG["symbol"])

                logger.info("✅ 清理完成")
            except Exception as e:
                logger.error(f"清理过程中出错: {e}")

        logger.info("网格交易机器人已停止")

    def cleanup(self):
        """清理资源"""
        self.running = False
        logger.info("资源清理完成")

    def manual_control(self):
        """手动控制接口"""
        print("\n=== 手动控制菜单 ===")
        print("1. 显示状态")
        print("2. 手动平仓")
        print("3. 取消所有订单")
        print("4. 重置风控冷却")
        print("5. 调整订单大小")
        print("6. 退出程序")

        while True:
            try:
                choice = input("\n请输入选项 (1-6): ").strip()

                if choice == "1":
                    self.show_status()
                elif choice == "2":
                    self.trader.close_position(GRVT_CONFIG["symbol"])
                    print("✅ 平仓指令已发送")
                elif choice == "3":
                    self.trader.cancel_all_orders(GRVT_CONFIG["symbol"])
                    print("✅ 取消所有订单指令已发送")
                elif choice == "4":
                    self.strategy.reset_risk_cooldown()
                    print("✅ 风控冷却已重置")
                elif choice == "5":
                    try:
                        new_size = float(input("请输入新的订单大小(BTC): "))
                        self.strategy.set_order_size(new_size)
                        print(f"✅ 订单大小已设置为 {new_size} BTC")
                    except ValueError:
                        print("❌ 请输入有效的数字")
                elif choice == "6":
                    self.stop()
                    sys.exit(0)
                else:
                    print("❌ 无效选项")

            except KeyboardInterrupt:
                print("\n返回主循环...")
                break
            except Exception as e:
                print(f"❌ 操作失败: {e}")


async def main():
    """主函数"""
    print("\n" + "=" * 60)
    print("🎯 GRVT BTC网格自动交易系统")
    print("=" * 60)
    print("作者: @ddazmon")
    print("说明: 基于GRVT API的BTC永续合约网格交易策略")
    print("=" * 60)

    # 创建机器人实例
    bot = GridTradingBot()

    # 运行主循环
    try:
        await bot.run()
    except KeyboardInterrupt:
        logger.info("收到键盘中断信号")
        bot.stop()
    except Exception as e:
        logger.error(f"程序异常退出: {e}", exc_info=True)
        bot.stop()


if __name__ == "__main__":
    asyncio.run(main())