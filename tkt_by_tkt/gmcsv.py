"""Tools for reading Google MyMaps layer export CSV"""

import csv

def read_map(file_handle):
    """Read a Google maps CSV map and return dictionary"""
    reader = csv.DictReader(file_handle)
    return {x['name']: tuple(float(y)
                             for y in x['WKT'].partition('(')[2].partition(')')[0].split())
            for x in reader}
