def BytesToMiB(b: int) -> int:
    return b / (1024 * 1024)

def BytesToGiB(b: int) -> int:
    return b / (1024 * 1024 * 1024)

def MiBToBytes(mib: int) -> int:
    return mib * (1024 * 1024)

def GiBToBytes(gib: int) -> int:
    return gib * (1024 * 1024 * 1024)
