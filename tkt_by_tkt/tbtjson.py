"""Tools for reading and writing TBT Map JSON"""

import json
from . import models

def write_map(map_obj, file_handle):
    """Write a map to JSON"""
    json.dump({"cities": map_obj.export_cities(),
               "routes": map_obj.export_routes()},
               file_handle, indent=2)

def read_map(file_handle):
    """Read a map from JSON"""
    raw = json.load(file_handle)
    my_map = models.Map()
    for city, latlng in raw.get('cities', {}).items():
        city_obj = my_map.add_city(city)
        city_obj.place(latlng)
    for route in raw.get('routes', []):
        route_obj = my_map.add_route(route['cities'])
        if route.get('length'):
            route_obj.set_length(route['length'])
        if route.get('tracks'):
            route_obj.set_tracks(route['tracks'])
    return my_map
