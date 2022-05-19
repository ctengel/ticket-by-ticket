"""Tools for reading and writing TBT Map JSON"""

import json

def write_map(map_obj, file_handle):
    """Write a map to JSON"""
    json.dump({"cities": map_obj.export_cities()}, file_handle, indent=2)
