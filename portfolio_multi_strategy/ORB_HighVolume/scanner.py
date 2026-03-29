"""
Stock Scanner for ORB Strategy

Scans for stocks meeting criteria:
- High volume (top percentile)
- ATR > 10% of price
- Price > $5
"""

import logging
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed
import SureshotSDK
from SureshotSDK.BacktestingPriceCache import BacktestingPriceCache
from SureshotSDK.utils import fetch_all_nasdaq_symbols

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_BACKTEST_CHUNK_SIZE = 10
_MAX_SCAN_WORKERS = 100 # default: 20 


class StockScanner:
    """
    Scans for high-volume, volatile stocks suitable for ORB trading
    """

    def __init__(
        self,
        min_price: float = 5.0,
        min_atr_percent: float = 10.0,
        atr_period: int = 14,
        volume_lookback_days: int = 20,
        price_cache: Optional[BacktestingPriceCache] = BacktestingPriceCache(),
        selector: str = 'avg_volume'
        # price_cache: Optional[BacktestingPriceCache] = None
    ):
        """
        Initialize scanner

        Args:
            min_price: Minimum stock price
            min_atr_percent: Minimum ATR as % of price
            atr_period: ATR calculation period
            volume_lookback_days: Days to look back for volume average
            price_cache: Optional price cache for backtest mode
        """
        self.min_price = min_price
        self.min_atr_percent = min_atr_percent
        self.atr_period = atr_period
        self.volume_lookback_days = volume_lookback_days
        self.polygon_client = SureshotSDK.PolygonClient()
        self.price_cache = price_cache
        self.selector = selector

    def get_rus2000_tickers(self) -> List[str]:
        """
        Get list of Russell 2000 tickers (1957 stocks as of Feb 2026).
        Source: data/russell_2000.csv
        """
        return [
            "BE", "CRDO", "FN", "KTOS", "NXT", "SATS", "HL", "GH", "IONQ",
            "CDE", "RMBS", "BBIO", "STRL", "AVAV", "DY", "TTMI", "SPXC", "MOD",
            "ENSG", "AEIS", "GTLS", "UMBF", "ARWR", "MDGL", "OKLO", "MOG.A", "CMC",
            "ONB", "IDCC", "LUMN", "RNA", "CTRE", "JXN", "UEC", "WTS", "JBTM",
            "APLD", "COMP", "PRIM", "AHR", "SITM", "PRAX", "ORA", "AXSM", "FLR",
            "SANM", "CYTK", "HQY", "QBTS", "EAT", "SMTC", "ZWS", "KRYS", "FCFS",
            "ENS", "CWAN", "IBP", "GKOS", "GATX", "GBCI", "FSS", "CWST", "PCVX",
            "TRNO", "PIPR", "VLY", "EPRT", "UFPI", "ESNT", "MIR", "PL", "TXNM",
            "ESE", "UBSI", "PTCT", "TMHC", "RHP", "HWC", "RGTI", "BIPC", "POR",
            "BCPC", "VSAT", "ACA", "HIMS", "AUB", "SNEX", "ALKS", "BOOT", "FORM",
            "HOMB", "OPCH", "RYTM", "VIAV", "RIOT", "AX", "SWX", "BKH", "PLXS",
            "BCO", "MMS", "HUT", "ABCB", "MC", "GVA", "LMND", "CORZ", "CIFR",
            "ROAD", "NUVL", "JOBY", "UUUU", "SIGI", "AROC", "KRG", "CNX", "NPO",
            "MATX", "VSEC", "NJR", "COGT", "STEP", "SR", "IRTC", "MRCY", "CRNX",
            "CNR", "NOVT", "SM", "MTH", "ATMU", "QLYS", "MAC", "RDNT", "OGS",
            "PTGX", "MMSI", "LEU", "HRI", "AGX", "HCC", "SSRM", "SLAB", "RIG",
            "MGY", "TCBI", "BDC", "PECO", "ABG", "ANF", "EBC", "ASB", "ACHR",
            "EOSE", "ITRI", "NE", "TMDX", "TDS", "ACIW", "LNTH", "RDN", "SBRA",
            "SKY", "REZI", "LTH", "CSW", "BTSG", "LAUR", "GPI", "CRSP", "BMI",
            "URBN", "FTDR", "BTU", "INDV", "FFIN", "TGTX", "FOLD", "RUN", "POWL",
            "MIRM", "SFBS", "MWA", "UCB", "HASI", "NWE", "AIR", "PATK", "KYMR",
            "MUR", "INDB", "WULF", "OSIS", "STNE", "CNO", "IRT", "FLG", "ADMA",
            "SXT", "ENVA", "PJT", "GLNG", "VISN", "CRC", "SKYW", "RUSHA", "LBRT",
            "WK", "FELE", "NHI", "MYRG", "WHD", "CBT", "KNF", "CVLT", "CVCO",
            "ALHC", "QTWO", "CWK", "IBOC", "KAI", "DOCN", "VSCO", "FULT", "GHC",
            "PI", "LGND", "AEO", "ATGE", "SIG", "CALM", "AZZ", "TEX", "SKT",
            "EXPO", "PSMT", "ASO", "SRRK", "KFY", "PRM", "KBH", "VICR", "WSFS",
            "ICUI", "LRN", "VAL", "OUT", "BKU", "LIVN", "BOX", "RNST", "KGS",
            "MARA", "FBP", "CELC", "TPC", "BNL", "CDP", "ZETA", "MHO", "BKD",
            "LCII", "VRNS", "MZTI", "SHAK", "GRAL", "OTTR", "IESC", "DORM", "PII",
            "CATY", "DAN", "SPSC", "GNW", "AVA", "UPST", "WSBC", "AVNT", "BFH",
            "CBU", "BGC", "KTB", "FUL", "CLSK", "HP", "PLMR", "GPOR", "SLG",
            "HAE", "SYNA", "PBH", "FIBK", "SOUN", "OPLN", "SHOO", "UNF", "WDFC",
            "ACAD", "GFF", "VCTR", "XENE", "REVG", "GSAT", "RRR", "CSTM", "VRRM",
            "TGNA", "TDW", "BXMT", "BCC", "HNI", "NMIH", "CPK", "ITGR", "VCYT",
            "OII", "TERN", "MGEE", "BOH", "ACMR", "SFNC", "WAY", "PFSI", "KLIC",
            "SBCF", "CGON", "FFBC", "LXP", "SXI", "AAP", "HURN", "DNLI", "STNG",
            "GTX", "MTRN", "PFS", "HUBG", "OSCR", "TPH", "AWR", "DNOW", "YOU",
            "CPRX", "ABM", "PBF", "ARQT", "APAM", "ADPT", "HGV", "MGRC", "ACLS",
            "NATL", "DBRG", "LQDA", "DIOD", "PHIN", "PRVA", "CALX", "CAKE", "TENB",
            "GOLF", "CWT", "HE", "CARG", "SPHR", "NG", "AKR", "BEAM", "NMRK",
            "VRDN", "AAOI", "CPRI", "KMT", "PTEN", "FCPT", "AMBA", "APLE", "SUPN",
            "GT", "CON", "IDYA", "CVBF", "POWI", "TOWN", "BANC", "TVTX", "HWKN",
            "COCO", "WAFD", "CUBI", "TARS", "APGE", "JOE", "TBBK", "WRBY", "VC",
            "XMTR", "UE", "UPWK", "CNK", "TWST", "NSIT", "AMR", "MSGE", "VSH",
            "BL", "SDRL", "PRK", "VERA", "NGVT", "INSW", "NOG", "CENX", "TRMK",
            "FBK", "PLUG", "RXO", "BBT", "CURB", "MCY", "OI", "ACLX", "FBNC",
            "ATKR", "SEI", "ATRO", "ALRM", "TRN", "IMNM", "CRGY", "BANF", "CHEF",
            "IVT", "FRME", "NBTB", "PLUS", "TSX:PPTA", "CC", "HI", "AGYS", "NEOG",
            "RELY", "UNFI", "TXG", "CSGS", "SMR", "OMCL", "PTON", "DYN", "SYRE",
            "BBAI", "MRX", "ASGN", "GRBK", "FRSH", "GEO", "CTRI", "NTB", "HLIO",
            "EPAC", "KWR", "LASR", "BANR", "EFSC", "TPB", "PRDO", "SPNT", "BELFB",
            "BUSE", "LUNR", "MTX", "WD", "KN", "ARCB", "AMRX", "BLKB", "EYE",
            "WERN", "CASH", "DX", "IOSP", "ANDE", "CRVL", "MGNI", "ALG", "TIC",
            "PAGS", "WT", "CECO", "STRA", "USAR", "PLAB", "KALU", "ADEA", "ARR",
            "OSW", "FLNC", "CXW", "UCTT", "BUR.L", "NTCT", "CBZ", "INTA", "DHT",
            "NIC", "LION", "EVTC", "IRON", "AVDL", "EXTR", "BULL", "LC", "NWN",
            "KSS", "GENI", "EWTX", "CALY", "DRH", "UFPT", "PARR", "FCF", "ADUS",
            "GNL", "STC", "NWBI", "QUBT", "BHE", "HLMN", "VECO", "MD", "IBRX",
            "ARDX", "QDEL", "BATRK", "TNET", "WGS", "HMN", "TILE", "ERAS", "IMVT",
            "IE", "NHC", "KNTK", "VCEL", "CRK", "SLNO", "PGNY", "IPAR", "ATRC",
            "GEF", "CNS", "SYBT", "PAYO", "OFG", "BRZE", "WLDN", "LMAT", "HLF",
            "DK", "ROG", "PRGS", "MNKD", "WOR", "STEL", "ATEC", "SMPL", "LGN",
            "HTO", "AUPH", "CHCO", "SNDX", "FUN", "ARRY", "AORT", "SONO", "ICFI",
            "HCI", "DEI", "AVPT", "DBD", "INOD", "OCUL", "DAVE", "ADNT", "DXPE",
            "SLVM", "PBI", "LTC", "YELP", "NRIX", "RCUS", "CCS", "AIN", "STBA",
            "HTH", "SEM", "RSI", "GTY", "CLDX", "HRMY", "SHO", "SKWD", "BLBD",
            "RXRX", "VVX", "DFTX", "SHLS", "AZTA", "NTST", "AGM", "RAMP", "DGII",
            "BWIN", "DCO", "DVAX", "LEG", "TALO", "NEO", "ZD", "TNK", "AGIO",
            "AXGN", "CENTA", "CLMT", "PRCT", "NSP", "MBC", "BCRX", "FTRE", "OLMA",
            "ROCK", "IMAX", "GABC", "GBX", "NBHC", "TRIP", "BRSL", "ALEX", "VAC",
            "LZB", "ARI", "SBH", "TCBK", "SGHC", "MQ", "SPB", "LKFN", "WVE",
            "ABR", "BKE", "QCRH", "ANIP", "THR", "AAMI", "PACS", "HOPE", "CTS",
            "FLYW", "REAL", "NNI", "JJSF", "GSHD", "ALKT", "WKC", "TTI", "JBLU",
            "MLYS", "COLL", "NVRI", "SPNS", "MXL", "TFIN", "WWW", "XPRO", "LOB",
            "TNC", "XHR", "UNIT", "PWP", "AI", "ALMS", "RCAT", "VYX", "CMPR",
            "MLKN", "AMPX", "NVTS", "UVV", "ENR", "FIVN", "BLX", "LNN", "NN",
            "STOK", "DCOM", "SILA", "GPGI", "NTLA", "TNDM", "PEB", "IIPR", "WINA",
            "TGLS", "HCSG", "NVAX", "DFIN", "WS", "ORKA", "FDP", "DOLE", "ACVA",
            "AMSC", "XPEL", "DNTH", "USLM", "COHU", "VERX", "UTI", "HROW", "FSLY",
            "BTDR", "ALGT", "PRG", "DHC", "OBK", "NSSC", "WLY", "CNOB", "AMLX",
            "USPH", "BFC", "NUVB", "ARLO", "ENOV", "NVCR", "INVA", "EFC", "UMH",
            "ATEN", "LADR", "PRLB", "WGO", "VTOL", "HG", "SRCE", "BORR", "SCL",
            "PCT", "ECPG", "THS", "PRA", "CCB", "TNGX", "CRI", "WABC", "ECVT",
            "CRAI", "NESR", "TWO", "CNMD", "ORC", "KW", "TRUP", "CCOI", "CRVS",
            "NNE", "LFST", "LIF", "DLX", "MCRI", "SAFT", "PZZA", "SGRY", "VRE",
            "WTTR", "GRC", "CDRE", "OUST", "PEBO", "NPKI", "LZ", "XERS", "ZYME",
            "ACT", "RVLV", "CSTL", "ENVX", "ASTE", "TE", "TRS", "BHVN", "HLX",
            "APPN", "LPG", "IMKTA", "HLIT", "FG", "CSR", "TMP", "RLAY", "MBIN",
            "SFL", "CDNA", "FA", "GIII", "FIHL", "OCFC", "PAR", "MBX", "VRTS",
            "PDM", "ELVN", "PMT", "ICHR", "SEZL", "LGIH", "AHCO", "PRKS", "EYPT",
            "RLJ", "UPB", "PDFS", "CIM", "JBGS", "AMRC", "PFBC", "BY", "OSBC",
            "PENG", "GLDD", "TSHA", "MFA", "DEA", "UPBD", "PGY", "VITL", "CTBI",
            "GOLD", "LILAK", "MIAX", "SMA", "GCT", "EIG", "WMK", "THRM", "REX",
            "TDOC", "PAX", "ALH", "INVX", "AMPH", "SKYT", "BV", "MSEX", "GLUE",
            "FIGS", "TRVI", "PD", "NBR", "BBSI", "EVLV", "STAA", "UVSP", "SCSC",
            "AAT", "PNTG", "MAZE", "SBSI", "JBI", "DRVN", "ESRT", "ASTH", "DCH",
            "PUMP", "CLB", "PCRX", "FMBH", "CLOV", "LMB", "AESI", "UTL", "GO",
            "SAH", "SNCY", "CFFN", "BLFS", "GBTG", "AMAL", "EE", "ASAN", "HBNC",
            "BHRB", "DAKT", "HFWA", "FWRG", "ALNT", "ARVN", "EPC", "DAWN", "ANAB",
            "UAMY", "NBBK", "RHLD", "COUR", "CMP", "NX", "RDW", "NBN", "CPF",
            "PLOW", "NAT", "AMWD", "XNCR", "MCB", "AMPL", "SMP", "BJRI", "CAPR",
            "FBRT", "CMPX", "FLNG", "TDAY", "LON:DEC", "TSX:BBUC", "MBWM", "PAHC", "FIZZ",
            "AMN", "CCNE", "PGEN", "METC", "TRST", "INDI", "BFST", "TYRA", "CAC",
            "HAFC", "IRMD", "EXPI", "JAMF", "CWH", "AMTB", "ESPR", "SAFE", "IDT",
            "LINC", "SDGR", "APOG", "MATW", "IOVA", "IRWD", "AIV", "UTZ", "BFLY",
            "UVE", "FOXF", "ESQ", "BRSP", "OMER", "GPRE", "PHR", "MYE", "RYI",
            "SVRA", "HTBK", "ROOT", "RPD", "MOFG", "RAPP", "UFCS", "ERII", "EGBN",
            "VSTS", "KOS", "GERN", "IART", "KOD", "LQDT", "FUBO", "CMRE", "THFF",
            "BBW", "DJCO", "PRSU", "SOC", "MEG", "QNST", "KE", "MTUS", "SANA",
            "AEHR", "GHM", "MCHB", "APEI", "YEXT", "TROX", "URGN", "JBIO", "AMC",
            "NEXT", "CXM", "MRTN", "TBPH", "AMSF", "SCHL", "EQBK", "CVI", "IBCP",
            "RWT", "INBX", "SLDP", "HTB", "TR", "BKSY", "ADTN", "PRCH", "CNNE",
            "GRDN", "ADAM", "NXRT", "ORIC", "SION", "ORRF", "STGW", "CBRL", "SXC",
            "NAVI", "AVBP", "NPK", "BKV", "VIR", "EVER", "GNK", "ALIT", "KURA",
            "FISI", "WASH", "CBL", "GDOT", "MMI", "CNXN", "SERV", "MATV", "PLPC",
            "BTBT", "CGEM", "MPB", "WSR", "HRTG", "SIBN", "NWPX", "FIP", "TCMD",
            "SG", "AIOT", "KFRC", "TREE", "NB", "RPC", "JBSS", "LIND", "ABUS",
            "ANNX", "PACB", "EMBC", "IIIN", "FSBC", "VTS", "IVR", "RIGL", "PSIX",
            "AMBP", "CARS", "CSV", "TRTX", "SEMR", "RBCAA", "RUM", "SMBC", "MDXG",
            "SHEN", "LYTS", "MBUU", "ODC", "VPG", "KALV", "FWRD", "CTLP", "CMCO",
            "AVNS", "CRML", "BZH", "RES", "EBS", "GCMG", "SPRY", "CTKB", "JANX",
            "ASPI", "TSXV:EU", "SHBI", "NVGS", "AVAH", "TALK", "SMBK", "CCBG", "HTFL",
            "HTZ", "ALRS", "ACEL", "AHL", "SD", "CRMD", "PKST", "AVO", "HNRG",
            "NTGR", "CWCO", "VREX", "GSM", "APPS", "FCBC", "SBGI", "MNRO", "AHH",
            "KOP", "BHB", "CTO", "SENEA", "PVLA", "MAMA", "AOSL", "TRNS", "GDYN",
            "MCBS", "AROW", "MCW", "CBLL", "RR", "AEBI", "TK", "PHAT", "HOV",
            "DFH", "FLY", "FLGT", "GOOD", "BBNX", "ZGN", "SFIX", "DC", "SPFI",
            "CASS", "HIPO", "ETD", "BXC", "EGY", "CPS", "HSTM", "BCAX", "RUSHB",
            "ALX", "EHAB", "KROS", "IIIV", "RGNX", "TCBX", "MVST", "ARHS", "OXM",
            "GDEN", "ACNB", "RGR", "NUS", "OPK", "DIN", "IDR", "NRDS", "RDVT",
            "OFIX", "GSBC", "HZO", "WLFC", "UHT", "NRIM", "MYGN", "NUTX", "PLAY",
            "FFIC", "PGC", "BLMN", "HIFS", "FOR", "ZVRA", "LXU", "RYAM", "SEPN",
            "TDUP", "FSUN", "PRAA", "ALT", "FRGE", "CEVA", "BWMN", "BDN", "REPL",
            "PFIS", "KMTS", "YORW", "SSTK", "SABR", "CARE", "SWBI", "AEVA", "OIS",
            "ZEUS", "EBF", "SPT", "FMNB", "CHCT", "MSBI", "INN", "PSNL", "BLND",
            "REAX", "ANGI", "LXEO", "SLS", "CYRX", "TWI", "RZLV", "FET", "FULC",
            "ORN", "SLDE", "CLMB", "UDMY", "CRNC", "CIVB", "HCKT", "HPP", "ABAT",
            "KOPN", "KREF", "AIP", "NFBK", "FBIZ", "GEVO", "MLR", "CMCL", "FPI",
            "BIOA", "PKE", "MITK", "MTW", "KRNY", "ASC", "CLBK", "HTLD", "GMRE",
            "CODI", "GIC", "TSX:SOY", "GOSS", "NABL", "BOW", "BSRR", "DHIL", "CERS",
            "NAVN", "CVGW", "MH", "SFST", "NXDR", "PSTL", "VOYG", "OSPN", "IMXI",
            "TTAM", "TIPT", "VNDA", "KRUS", "LAB", "NATR", "FLOC", "CABO", "MAGN",
            "ASIX", "REPX", "MLAB", "LBRX", "LTBR", "CYH", "RRBI", "COFS", "ABSI",
            "ANGO", "HBCP", "BBBY", "LXFR", "BCAL", "CAL", "CCSI", "CWBC", "ARKO",
            "BWB", "OPTU", "WNC", "FFWM", "SVV", "GTN", "BMRC", "OLP", "WEAV",
            "UNTY", "IHRT", "HY", "AVXL", "CSE:DRUG", "ULCC", "CZNC", "GEF.B", "BFS",
            "MTRX", "PRTA", "SATL", "BAND", "EVGO", "NPCE", "ETON", "CLNE", "CTOS",
            "SLDB", "LAND", "HELE", "PRME", "EVEX", "PTLO", "EVH", "CVLG", "IBEX",
            "DNA", "GRND", "ITIC", "JACK", "MRVI", "BVS", "GLRE", "WRLD", "FRBA",
            "OBT", "GRPN", "CBNK", "WTBA", "GOGO", "AKBA", "FDMT", "NPB", "IPI",
            "KODK", "NGS", "ENTA", "MGPI", "NGVC", "MOV", "MAX", "ZBIO", "FEIM",
            "SCVL", "MGTX", "MCS", "TITN", "OEC", "CLFD", "ACCO", "MCFT", "HVT",
            "FMAO", "BGS", "BWFG", "CLPT", "TRC", "FVR", "RBB", "RM", "EB",
            "SRTA", "CLDT", "KELYA", "PDLB", "CBAN", "NMAX", "PLBC", "VLGEA", "NVEC",
            "VSTM", "TRDA", "ZUMZ", "ACRS", "STRT", "NAGE", "RC", "MVBF", "CTGO",
            "SPIR", "DGICA", "TSX:VOXR", "ADCT", "CDZI", "RNGR", "HBT", "AQST", "SVC",
            "BATRA", "SITC", "FSTR", "OSL:HSHP", "BELFA", "RXST", "NEWT", "NWFL", "AVIR",
            "ABX", "ONIT", "MPLT", "OOMA", "BCML", "ONTF", "ATEX", "KIDS", "RCKT",
            "DCTH", "FNLC", "HLLY", "SB", "GBFH", "BYND", "NATH", "MBI", "NECB",
            "CCRN", "NLOP", "ALDX", "TLS", "TSBK", "GNE", "IBTA", "GCO", "CENT",
            "CZFS", "BRBS", "ILPT", "LOCO", "SWIM", "ALLO", "KFS", "FRST", "SLP",
            "SPOK", "QTRX", "DDD", "PBYI", "DSGR", "FRPH", "WSBF", "MNPR", "HDSN",
            "ACRE", "ATLC", "SIGA", "PUBM", "ORGO", "DMAC", "GRNT", "FSBW", "PKBK",
            "SMC", "RZLT", "ACIC", "MEI", "BOC", "JOUT", "BH", "PESI", "SGHT",
            "VMD", "CLW", "JMSB", "ISTR", "XRX", "MEC", "XPER", "AGL", "CADL",
            "LENZ", "HYLN", "OPFI", "CHMG", "CMTG", "PANL", "AVNW", "BLZE", "CIA",
            "TARA", "BYRN", "FTK", "JRVR", "AURA", "MITT", "RBBN", "PLSE", "MBCN",
            "MVIS", "PCB", "BRCB", "INR", "PAL", "RLGT", "DSGN", "BMBL", "XOMA",
            "WNEB", "EOLS", "DNUT", "ASUR", "LFCR", "NRC", "PCYO", "ASLE", "LMNR",
            "VIA", "ATNI", "NCMI", "CRSR", "AMCX", "PACK", "BLFY", "RPAY", "RMR",
            "USNA", "OSG", "FVCB", "CD", "NFE", "KRMD", "VEL", "ALCO", "ATLO",
            "PINE", "JELD", "FBLA", "HNST", "FUNC", "LCNB", "CFFI", "CHRS", "LILA",
            "TG", "ASST", "RCKY", "NKSH", "REFI", "CATX", "ASPN", "INSE", "PSFE",
            "ABEO", "OLPX", "EGHT", "TH", "USCB", "OPRT", "PKOH", "TECX", "FC",
            "OVLY", "BKTI", "XPOF", "WBTN", "FCCO", "CRCT", "WTI", "TSSI", "WOOF",
            "SNBR", "FRAF", "WYFI", "SSP", "FDBC", "NEXN", "DBI", "KRT", "CMRC",
            "MYFW", "USAU", "CTRN", "ALMU", "HWBK", "CTEV", "FXNC", "PLTK", "AVR",
            "HRTX", "ALTI", "CNDT", "ELMD", "SNWV", "TNXP", "SLQT", "STRS", "DOUG",
            "OSUR", "DOMO", "SKYH", "PDYN", "NC", "III", "RICK", "VABK", "LDI",
            "TBRG", "WEYS", "BKKT", "OABI", "FCAP", "SEVN", "FHTX", "FSFG", "ARDT",
            "ARCT", "BPRN", "BSVN", "TBCH", "GLSI", "LNKB", "IMMR", "EVC", "TOI",
            "UTMD", "CRMT", "CBK", "VYGR", "BNTC", "LPRO", "EDIT", "RGCO", "THRY",
            "SKYX", "VUZI", "QSI", "FENC", "EVCM", "CRD.A", "QUAD", "LEGH", "MDWD",
            "LOVE", "NXDT", "VTEX", "MG", "EFSI", "UIS", "DSP", "MRBK", "SNDA",
            "NNOX", "KINS", "WEST", "NGNE", "MASS", "LRMR", "CZWI", "SKIN", "OPRX",
            "BETR", "INBK", "PLX", "JCAP", "RMNI", "MFIN", "ACH", "BOOM", "EGAN",
            "AARD", "FNKO", "MPAA", "JAKK", "OPBK", "GCBC", "LE", "FINW", "CBFV",
            "PRTH", "EBMT", "MPTI", "BRT", "CMT", "OVBC", "PBFS", "BVFL", "HUMA",
            "PEBK", "ZIP", "RSVR", "TBI", "CURI", "ALEC", "PXED", "LAW", "TLSI",
            "TTGT", "ONEW", "MNSB", "TCX", "ACDC", "AII", "UBFO", "FFAI", "ESCA",
            "GENC", "BALY", "KLC", "BHR", "KLTR", "LZM", "RELL", "SMHI", "HCAT",
            "CMDB", "PAYS", "GETY", "BNED", "MDV", "SNFCA", "RMAX", "FLXS", "AMBQ",
            "RGP", "POWW", "SEG", "KULR", "ACU", "INGN", "OMDA", "JYNT", "INSG",
            "CFBK", "WHG", "ACTG", "HBB", "ACNT", "ECBK", "ALTG", "STXS", "FRD",
            "COSO", "SBFG", "EVI", "AVD", "FATE", "BSET", "LARK", "BBCP", "LFMD",
            "FNWD", "NVCT", "EPM", "MED", "ELDN", "SRBK", "BCBP", "AOMR", "LNSR",
            "CXDO", "DERM", "TSX:KEI", "TRAK", "FOA", "ACR", "OFLX", "MNTK", "MLP",
            "RMBI", "RPT", "ANIK", "STRZ", "EWCZ", "ASIC", "KRO", "JILL", "ARQ",
            "CLAR", "NREF", "LWAY", "INNV", "AOUT", "TMCI", "CDXS", "CVRX", "HAIN",
            "SGC", "GWRS", "CRDF", "ULH", "SPWR", "EML", "LUCD", "ESOA", "PNBK",
            "BZAI", "RVSB", "HNVR", "ZVIA", "RCMT", "ADV", "SAMG", "HPK", "TCI",
            "FLWS", "STRW", "EPSN", "DMRC", "GYRE", "SUNS", "SMID", "NKTX", "SFBC",
            "NODK", "FORR", "MXCT", "UNB", "IKT", "ELA", "GAMB", "INV", "KRRO",
            "ATOM", "EXFY", "FBYD", "LVWR", "ATYR", "MPX", "AVBH", "CARL", "FF",
            "PDEX", "AIRO", "STIM", "SNCR", "BARK", "CPSS", "OM", "EHTH", "ARAY",
            "CSPI", "VIRC", "PNRG", "LAKE", "AIRJ", "PMTS", "HFFG", "CBNA", "BRCC",
            "WALD", "AEYE", "NPWR", "RNAC", "AISP", "EEX", "DH", "ISPR", "MAPS",
            "DCGO", "SSTI", "SMTI", "SI", "FSP", "TTEC", "LUNG", "HQI", "FTLF",
            "LFT", "BTMD", "NRDY", "LFVN", "TUSK", "MYPS", "GAIA", "AFRI", "ANDG",
            "RCEL", "SWKH", "EQPT", "PROP", "RBKB", "SBC", "PAMT", "NL", "RXT",
            "AREN", "LMRI", "AIRS", "OPAL", "CLPR", "SKIL", "ACTU", "EP", "SIEB",
            "BEEP", "CURV", "EVMN", "COOK", "SVCO", "TZOO", "CIX", "VHI", "BETA",
            "NXXT", "MKTW", "INMB", "KG", "VALU", "USGO", "MYO", "CV", "TKNO",
            "SLSN", "TEAD", "LIFE", "YSS", "SEAT", "SLND", "ARL", "NEON", "VRM",
            "TVRD", "GOCO", "ATLN", "HURA", "AKTS", "BTGO", "FLYX", "GMGI", "TSE",
            "TVGN", "FLD", "LPA", "PMI", "SAFX", "VGAS", "ARAI", "ZSPC", "ELME",
            "THRD", "GENVR", "BBBY.WS", "SBT",
        ]

    def get_sp500_tickers(self) -> List[str]:
        """
        Get list of S&P 500 tickers (503 stocks as of Feb 2026).
        Source: https://stockanalysis.com/list/sp-500-stocks/
        """
        return [
            "NVDA", "AAPL", "GOOGL", "GOOG", "MSFT", "AMZN", "META", "AVGO", "TSLA",
            "BRK.B", "WMT", "LLY", "JPM", "XOM", "V", "JNJ", "MU", "MA", "COST",
            "ORCL", "ABBV", "NFLX", "PG", "HD", "CVX", "GE", "BAC", "KO", "CAT",
            "PLTR", "AMD", "CSCO", "MRK", "AMAT", "LRCX", "PM", "RTX", "UNH", "GS",
            "MS", "WFC", "MCD", "TMUS", "GEV", "LIN", "PEP", "INTC", "IBM", "AXP",
            "VZ", "AMGN", "ABT", "KLAC", "T", "NEE", "TMO", "C", "TXN", "DIS",
            "GILD", "CRM", "APH", "TJX", "ISRG", "BA", "ADI", "BLK", "DE", "ANET",
            "SCHW", "UNP", "PFE", "UBER", "HON", "QCOM", "LMT", "DHR", "LOW", "SYK",
            "APP", "ETN", "WELL", "NEM", "BX", "COP", "PLD", "BKNG", "CB", "SPGI",
            "GLW", "ACN", "PH", "BMY", "VRTX", "MDT", "PGR", "COF", "PANW", "MCK",
            "CEG", "HCA", "MO", "CME", "BSX", "INTU", "NOW", "SBUX", "CMCSA", "SO",
            "ADBE", "HWM", "NOC", "TT", "DUK", "CVS", "UPS", "DELL", "FCX", "WM",
            "GD", "EQIX", "WDC", "SNDK", "CRWD", "ICE", "NKE", "STX", "WMB", "FDX",
            "MAR", "MRSH", "AMT", "SHW", "JCI", "MMM", "ECL", "ADP", "PNC", "USB",
            "EMR", "MCO", "PWR", "RCL", "ITW", "MNST", "CDNS", "BK", "ABNB", "CMI",
            "CTAS", "REGN", "CRH", "MSI", "CL", "CSX", "SNPS", "ORLY", "MDLZ", "KKR",
            "SPG", "SLB", "DASH", "CI", "KMI", "CVNA", "TDG", "COR", "AEP", "AON",
            "HLT", "GM", "RSG", "NSC", "ELV", "WBD", "HOOD", "LHX", "TEL", "TRV",
            "EOG", "ROST", "PCAR", "BKR", "SRE", "O", "AZO", "DLR", "PSX", "TFC",
            "APD", "VLO", "APO", "AJG", "VST", "FTNT", "MPC", "AFL", "NXPI", "F",
            "ALL", "MPWR", "D", "ZTS", "AME", "GWW", "PSA", "CAH", "CTVA", "CARR",
            "URI", "FAST", "KEYS", "OXY", "IDXX", "OKE", "ADSK", "XEL", "TGT", "TRGP",
            "EXC", "BDX", "EW", "FIX", "EA", "TER", "NDAQ", "CIEN", "FANG", "GRMN",
            "ETR", "CMG", "HSY", "MET", "YUM", "DHI", "COIN", "ROK", "WAB", "FITB",
            "SYY", "CCL", "AXON", "TKO", "AIG", "KR", "PEG", "CBRE", "AMP", "DAL",
            "PYPL", "ODFL", "MSCI", "PCG", "VTR", "KDP", "MLM", "EBAY", "ED", "VMC",
            "MCHP", "NUE", "DDOG", "EL", "TTWO", "CCI", "HIG", "NRG", "GEHC", "EQT",
            "XYZ", "LVS", "WEC", "LYV", "RMD", "KMB", "ARES", "CPRT", "IR", "KVUE",
            "TPL", "ROP", "OTIS", "STT", "ACGL", "WDAY", "DG", "UAL", "A", "PRU",
            "HBAN", "PAYX", "FICO", "CHTR", "EXR", "FISV", "ADM", "MTB", "VICI", "EME",
            "IRM", "IBKR", "TDY", "XYL", "TPR", "CBOE", "WAT", "AEE", "ATO", "CTSH",
            "DTE", "DOV", "ULTA", "IQV", "RJF", "HAL", "FE", "ROL", "PPL", "KHC",
            "WTW", "EIX", "VRSK", "ES", "HPE", "CNP", "LEN", "DXCM", "STLD", "BIIB",
            "JBL", "MTD", "PPG", "STZ", "TSCO", "HUBB", "WRB", "DVN", "NTRS", "AWK",
            "Q", "OMC", "EXPE", "PHM", "FIS", "ON", "EXE", "CFG", "CINF", "DLTR",
            "EFX", "CHD", "AVB", "STE", "DRI", "WSM", "SW", "EQR", "BRO", "LUV",
            "VLTO", "GIS", "RF", "SYF", "FOXA", "CMS", "LH", "BG", "DGX", "CTRA",
            "IP", "HUM", "FOX", "TSN", "CPAY", "L", "NI", "KEY", "AMCR", "LDOS",
            "DOW", "JBHT", "CNC", "CHRW", "RL", "LULU", "BR", "GPN", "SBAC", "FSLR",
            "MRNA", "IFF", "ALB", "NVR", "VRSN", "PFG", "TROW", "PKG", "DD", "INCY",
            "SNA", "LII", "NTAP", "SMCI", "EXPD", "EVRG", "ZBH", "MKC", "CSGP", "PTC",
            "LNT", "LYB", "WST", "FTV", "BALL", "WY", "HII", "HPQ", "PODD", "VTRS",
            "TXT", "ESS", "HOLX", "DECK", "GPC", "COO", "NDSN", "PNR", "J", "INVH",
            "MAA", "KIM", "CDW", "APTV", "TRMB", "IEX", "CLX", "FFIV", "CF", "TYL",
            "PSKY", "AVY", "REG", "MAS", "AKAM", "ERIE", "HRL", "HAS", "NWS", "ALLE",
            "BEN", "GEN", "HST", "ALGN", "EG", "DPZ", "UDR", "NWSA", "SWK", "BF.B",
            "GNRC", "BBY", "SOLV", "UHS", "DOC", "SJM", "AES", "PNW", "JKHY", "IVZ",
            "GDDY", "CPT", "BLDR", "TTD", "GL", "AIZ", "NCLH", "WYNN", "IT", "ZBRA",
            "RVTY", "AOS", "APA", "BAX", "DVA", "BXP", "HSIC", "FRT", "MGM", "ARE",
            "TECH", "CAG", "TAP", "SWKS", "MOS", "CRL", "POOL", "FDS", "CPB", "MOH",
            "EPAM", "MTCH", "LW", "PAYC",
        ]

    def _fetch_from_api(self, symbol: str, start_date: datetime, end_date: datetime, timeframe: str) -> List[Dict]:
        """Fetch price data from Polygon API (used as callback for cache)"""
        return self.polygon_client.get_historical_data(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            timeframe=timeframe
        )

    def _get_bars(self, symbol: str, start_date: datetime, end_date: datetime, timeframe: str = "1d") -> List[Dict]:
        """Get price bars using cache if available, otherwise fetch and cache"""
        if self.price_cache:
            cached = self.price_cache.get(
                symbol, start_date, end_date, timeframe,
                fetch_fn=self._fetch_from_api
            )
            if cached:
                return cached

        bars = self._fetch_from_api(symbol, start_date, end_date, timeframe)

        if bars and self.price_cache:
            self.price_cache.set(symbol, start_date, end_date, timeframe, bars)

        return bars

    def calculate_atr_percent(self, symbol: str, end_date: datetime = None) -> Optional[float]:
        """
        Calculate ATR as percentage of current price

        Args:
            symbol: Stock symbol

        Returns:
            ATR percentage or None if unable to calculate
        """
        try:
            # Get recent data for ATR calculation
            if not end_date:
                end_date = datetime.now()
            start_date = end_date - timedelta(days=self.atr_period + 10)

            bars = self._get_bars(symbol, start_date, end_date, "1d")

            if not bars or len(bars) < self.atr_period:
                return None

            # Calculate ATR
            atr = SureshotSDK.ATR(symbol, self.atr_period)

            for bar in bars:
                atr.Update(bar.get('h', bar.get('high')), bar.get('l', bar.get('low')), bar.get('c', bar.get('close')))

            atr_value = atr.get_value()
            current_price = bars[-1].get('c', bars[-1].get('close'))

            if current_price == 0:
                return None

            atr_percent = (atr_value / current_price) * 100

            return atr_percent

        except Exception as e:
            logger.error(f"Error calculating ATR for {symbol}: {e}")
            return None

    def get_average_volume(self, symbol: str, end_date: datetime = None) -> Optional[float]:
        """
        Get average volume over lookback period

        Args:
            symbol: Stock symbol

        Returns:
            Average volume or None if unable to calculate
        """
        try:
            if not end_date:
                end_date = datetime.now()
            start_date = end_date - timedelta(days=self.volume_lookback_days + 20)

            bars = self._get_bars(symbol, start_date, end_date, "1d")

            if not bars:
                logger.error(f"No candles returned from volume data request")
                return None
            if len(bars) < self.volume_lookback_days:
                logger.error("Insufficient data returned to find average volume")
                return None

            volumes = [bar['v'] for bar in bars[-self.volume_lookback_days:]]
            avg_volume = sum(volumes) / len(volumes)

            return avg_volume

        except Exception as e:
            logger.error(f"Error getting volume for {symbol}: {e}")
            return None

    def get_current_price(self, symbol: str, current_date: datetime = None) -> Optional[float]:
        """Get current price for symbol"""
        try:
            if current_date:
                # Use 1d close for backtest — already in memory, no disk I/O
                bars = self._get_bars(symbol, current_date - timedelta(weeks=1), current_date, "1d")
                if bars:
                    return bars[-1].get('c', bars[-1].get('close'))
                return None
            price = self.polygon_client.get_current_price(symbol)
            return price
        except Exception as e:
            logger.error(f"Error getting price for {symbol}: {e}")
            return None

    def _evaluate_ticker(self, symbol: str, current_date: datetime) -> Optional[Dict]:
        """Evaluate a single ticker against all scan criteria."""
        logger.debug(f"Scanning {symbol}...")

        price = self.get_current_price(symbol, current_date)
        if not price or price < self.min_price:
            logger.debug(f"  {symbol}: Price ${price} below minimum")
            return None

        atr_percent = self.calculate_atr_percent(symbol, current_date)
        if not atr_percent or atr_percent < self.min_atr_percent:
            logger.debug(f"  {symbol}: ATR% {atr_percent}% below minimum")
            return None

        avg_volume = self.get_average_volume(symbol, current_date)
        if not avg_volume:
            logger.debug(f"  {symbol}: Unable to get volume data")
            return None

        logger.debug(f"  {symbol}: Price ${price:.2f}, ATR {atr_percent:.2f}%, Vol {avg_volume:,.0f}")
        return {
            'symbol': symbol,
            'price': price,
            'atr_percent': atr_percent,
            'avg_volume': avg_volume,
        }

    def _scan_chunk(self, symbols: List[str], current_date: datetime, pbar=None) -> List[Dict]:
        """Evaluate a chunk of tickers. Uses its own PolygonClient instance for thread safety."""
        chunk_scanner = StockScanner(
            min_price=self.min_price,
            min_atr_percent=self.min_atr_percent,
            atr_period=self.atr_period,
            volume_lookback_days=self.volume_lookback_days,
            price_cache=self.price_cache,
            selector=self.selector,
        )
        results = []
        for symbol in symbols:
            try:
                candidate = chunk_scanner._evaluate_ticker(symbol, current_date)
                if candidate:
                    results.append(candidate)
            except Exception as e:
                logger.error(f"Error evaluating {symbol}: {e}")
            finally:
                if pbar:
                    pbar.update(1)
        return results

    def scan(self, max_candidates: int = 5, current_date: datetime = None) -> List[Dict]:
        # TODO: Rename this or add "filter"/"sort" to scan by
        # volume, ATR, Price, ... and filter by other metrics
        """
        Scan for top candidates

        Args:
            max_candidates: Maximum number of stocks to return

        Returns:
            List of dicts with symbol, price, atr_percent, avg_volume
        """
        logger.info(f"Scanning for stocks with min price ${self.min_price}, min ATR {self.min_atr_percent}%...")

        # tickers = self.get_sp500_tickers()
        tickers = self.get_rus2000_tickers()
        # tickers = fetch_all_nasdaq_symbols()
        # tickers = ['GOOGL','AAPL','TSLA','F','T',
        #            'NVDA', 'TSLA', 'AMD', 'AMZN', 'MSFT',
        #            'META','PLTR','BAC','F','INTC',
        #            'MU','SNDK','NFLX','JPM','C',
        #            'WFC','SOFI','SNAP']

        candidates = []

        if current_date is not None and len(tickers) >= 100:
            # Parallel backtest mode: split into chunks of _BACKTEST_CHUNK_SIZE
            chunks = [tickers[i:i + _BACKTEST_CHUNK_SIZE] for i in range(0, len(tickers), _BACKTEST_CHUNK_SIZE)]
            max_workers = min(len(chunks), _MAX_SCAN_WORKERS)
            logger.info(f"Parallel backtest scan: {len(tickers)} tickers → {len(chunks)} chunks, {max_workers} workers")

            with tqdm(total=len(tickers), desc="Scanning tickers") as pbar:
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    chunk_jobs = {executor.submit(self._scan_chunk, chunk, current_date, pbar): chunk for chunk in chunks}
                    for chunk_job in as_completed(chunk_jobs):
                        try:
                            candidates.extend(chunk_job.result())
                        except Exception as e:
                            logger.error(f"Chunk scan failed: {e}")
        else:
            # Sequential mode (live trading or small ticker list)
            for symbol in tqdm(tickers):
                candidate = self._evaluate_ticker(symbol, current_date)
                if candidate:
                    candidates.append(candidate)

        # Sort by selector metric and return top N
        candidates.sort(key=lambda x: x[self.selector], reverse=True)
        top_candidates = candidates[:max_candidates]

        logger.info(f"Found {len(top_candidates)} candidates:")
        for i, c in enumerate(top_candidates, 1):
            logger.info(f"  {i}. {c['symbol']}: ${c['price']:.2f}, ATR {c['atr_percent']:.1f}%, Vol {c['avg_volume']:,.0f}")

        return top_candidates

    def get_top_candidate(self, current_date: datetime = None) -> Optional[str]:
        """
        Get the single best candidate symbol

        Returns:
            Symbol of top candidate or None
        """
        candidates = self.scan(max_candidates=1, current_date=current_date)

        if candidates:
            return candidates[0]['symbol']
        else:
            return None

    def get_candidates(self, max_candidates: int = 1) -> Optional[str]:
        """
        Get the single best candidate symbol

        Returns:
            Symbol of top candidate or None
        """
        candidates = self.scan(max_candidates=max_candidates)

        if candidates:
            return candidates
        else:
            return None
