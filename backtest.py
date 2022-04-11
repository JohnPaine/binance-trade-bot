from datetime import datetime
from binance_trade_bot.logger import Logger
from binance_trade_bot import backtest
from sqlitedict import SqliteDict
from sortedcontainers import SortedDict
from dataclasses import dataclass
import itertools

cache = SqliteDict("data/backtest_cache.db")

logger = Logger("backtesting", enable_notifications=False)

# all_coins = ["DOT", "ADA"]
# all_coins = ["DOT", "ADA", "MATIC", "FTM", "TRX"]
all_coins = ["ETH", "BNB", "ETC", "XLM", "ADA", "DOT", "MATIC", "FTM", "TRX"]
# all_coins = ["ETH", "BNB", "ETC"]
# all_coins = ["ETH", "BNB", "ETC", "XLM"]

# all_coins = [
#     "BTC","LTC","ETH","NEO","BNB","QTUM","EOS","SNT","BNT","GAS","BCC","USDT","HSR","OAX","DNT","MCO","ICN","ZRX","OMG","WTC","YOYO","LRC","TRX","SNGLS","STRAT","BQX","FUN","KNC","CDT","XVG","IOTA","SNM","LINK","CVC","TNT","REP","MDA","MTL","SALT","NULS","SUB","STX","MTH","ADX","ETC","ENG","ZEC","AST","GNT","DGD","BAT","DASH","POWR","BTG","REQ","XMR","EVX","VIB","ENJ","VEN","ARK","XRP","MOD","STORJ","KMD","RCN","EDO","DATA","DLT","MANA","PPT","RDN","GXS","AMB","ARN","BCPT","CND","GVT","POE","BTS","FUEL","XZC","QSP","LSK","BCD","TNB","ADA","LEND","XLM","CMT","WAVES","WABI","GTO","ICX","OST","ELF","AION","WINGS","BRD","NEBL","NAV","VIBE","LUN","TRIG","APPC","CHAT","RLC","INS","PIVX","IOST","STEEM","NANO","AE","VIA","BLZ","SYS","RPX","NCASH","POA","ONT","ZIL","STORM","XEM","WAN","WPR","QLC","GRS","CLOAK","LOOM","BCN","TUSD","ZEN","SKY","THETA","IOTX","QKC","AGI","NXS","SC","NPXS","KEY","NAS","MFT","DENT","IQ","ARDR","HOT","VET","DOCK","POLY","VTHO","ONG","PHX","HC","GO","PAX","RVN","DCR","USDC","MITH","BCHABC","BCHSV","REN","BTT","USDS","FET","TFUEL","CELR","MATIC","ATOM","PHB","ONE","FTM","BTCB","USDSB","CHZ","COS","ALGO","ERD","DOGE","BGBP","DUSK","ANKR","WIN","TUSDB","COCOS","PERL","TOMO","BUSD","BAND","BEAM","HBAR","XTZ","NGN","DGB","NKN","GBP","EUR","KAVA","RUB","UAH","ARPA","TRY","CTXC","AERGO","BCH","TROY","BRL","VITE","FTT","AUD","OGN","DREP","BULL","BEAR","ETHBULL","ETHBEAR","XRPBULL","XRPBEAR","EOSBULL","EOSBEAR","TCT","WRX","LTO","ZAR","MBL","COTI","BKRW","BNBBULL","BNBBEAR","HIVE","STPT","SOL","IDRT","CTSI","CHR","BTCUP","BTCDOWN","HNT","JST","FIO","BIDR","STMX","MDT","PNT","COMP","IRIS","MKR","SXP","SNX","DAI","ETHUP","ETHDOWN","ADAUP","ADADOWN","LINKUP","LINKDOWN","DOT","RUNE","BNBUP","BNBDOWN","XTZUP","XTZDOWN","AVA","BAL","YFI","SRM","ANT","CRV","SAND","OCEAN","NMR","LUNA","IDEX","RSR","PAXG","WNXM","TRB","EGLD","BZRX","WBTC","KSM","SUSHI","YFII","DIA","BEL","UMA","EOSUP","TRXUP","EOSDOWN","TRXDOWN","XRPUP","XRPDOWN","DOTUP","DOTDOWN","NBS","WING","SWRV","LTCUP","LTCDOWN","CREAM","UNI","OXT","SUN","AVAX","BURGER","BAKE","FLM","SCRT","XVS","CAKE","SPARTA","UNIUP","UNIDOWN","ALPHA","ORN","UTK","NEAR","VIDT","AAVE","FIL","SXPUP","SXPDOWN","INJ","FILDOWN","FILUP","YFIUP","YFIDOWN","CTK","EASY","AUDIO","BCHUP","BCHDOWN","BOT","AXS","AKRO","HARD","KP3R","RENBTC","SLP","STRAX","UNFI","CVP","BCHA","FOR","FRONT","ROSE","HEGIC","AAVEUP","AAVEDOWN","PROM","BETH","SKL","GLM","SUSD","COVER","GHST","SUSHIUP","SUSHIDOWN","XLMUP","XLMDOWN","DF","JUV","PSG","BVND","GRT","CELO","TWT","REEF","OG","ATM","ASR","1INCH","RIF","BTCST","TRU","DEXE","CKB","FIRO","LIT","PROS","VAI","SFP","FXS","DODO","AUCTION","UFT","ACM","PHA","TVK","BADGER","FIS","OM","POND","ALICE","DEGO","BIFI","LINA"
# ]

dt1 = datetime(2022, 1, 1)
dt2 = datetime(2022, 4, 1)
balance = 100


@dataclass
class ShallowTestStats:
    usdt_val: float
    usdt_diff: float
    btc_val: float
    btc_diff: float
    coin_list: [str]


def gen_test_data(comb_sizes=None):
    if comb_sizes is None:
        comb_sizes = [2, 3, 4]
    d = []
    for size in comb_sizes:
        coin_list = [p for p in itertools.combinations(all_coins, size)]
        for coin_pair in coin_list:
            d.append({"coins": coin_pair, "DT1": dt1, "DT2": dt2, "usdt": balance})
    return d


def print_stats(stats, list_num, list_size):
    i = len(stats)
    if list_num >= list_size:
        logger.info(f"\n\n\n--->>> FINAL [{list_num}/{list_size}] Tests results:")
    else:
        logger.info(f"\n--------------------------->>> Tests results [{list_num}/{list_size}]:")

    for s in stats.values():
        rounded = round(s.usdt_val, 2)
        logger.info(f"{i}. {rounded}$: [coins: {s.coin_list}, usd_diff: {s.usdt_diff}%, btc_val: {s.btc_val}, "
                    f"btc_diff: {s.btc_diff}%]")
        i -= 1


def main():
    history = []

    stats = SortedDict()
    # test_data = gen_test_data([4, 6, 8])
    test_data = gen_test_data([2, 3, 4, 5, 6])
    size = len(test_data)

    logger.info(f"\n======================== Starting back-test on {size} coins combinations: ========================")
    for d in test_data:
        logger.info(d["coins"])

    i = 0
    for data in test_data:
        logger.info(f"\n    >>>--->>> Start back-testing on data [{i + 1}/{size}]: {data}")
        data_stats = []
        for manager in backtest(data["DT1"], data["DT2"], start_balances={"USDT": data["usdt"]},
                                supported_coins=data["coins"], logger=logger, cache=cache):
            btc_value = manager.collate_coins("BTC")
            bridge_value = manager.collate_coins(manager.config.BRIDGE.symbol)
            history.append((btc_value, bridge_value))
            btc_diff = round((btc_value - history[0][0]) / history[0][0] * 100, 3)
            bridge_diff = round((bridge_value - history[0][1]) / history[0][1] * 100, 3)

            data_stats = [bridge_value, bridge_diff, btc_value, btc_diff]

            print("------")
            print("TIME:", manager.datetime)
            print("BALANCES:", manager.balances)
            print("BTC VALUE:", btc_value, f"({btc_diff}%)")
            print(f"{manager.config.BRIDGE.symbol} VALUE:", bridge_value, f"({bridge_diff}%)")
            print("------")

        if data_stats:
            key = data_stats[0]
            while stats.__contains__(key):
                key += 1e-12
            stats[key] = ShallowTestStats(*data_stats, data["coins"])

        print_stats(stats, i, size)
        cache.commit()
        i += 1

    print_stats(stats, size, size)

    cache.close()


if __name__ == "__main__":
    main()
