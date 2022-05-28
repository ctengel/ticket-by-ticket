"""Tools for reading Google MyMaps layer export CSV"""

import csv

def read_map(file_handle):
    """Read a Google maps CSV map and return dictionary"""
    reader = csv.DictReader(file_handle)
    # NOTE we need to reverse since Google puts long, lat vs lat, long
    # NOTE sometimes Google sends an incorrect newline which confuses us hence the "if WKT"
    return {x['name']: tuple(reversed([float(y) for y
                                       in x['WKT'].partition('(')[2].partition(')')[0].split()]))
            for x in reader if x['WKT']}
