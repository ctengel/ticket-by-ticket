"""Allow exporting to SVG"""

import xml.etree.ElementTree as ET
import math

def deg2num(lat_deg, lon_deg, zoom):
    """Find a tile"""
    # see https://wiki.openstreetmap.org/wiki/Slippy_map_tilenames#Lon./lat._to_tile_numbers_2
    lat_rad = math.radians(lat_deg)
    n = 2.0 ** zoom
    xtile = int((lon_deg + 180.0) / 360.0 * n)
    ytile = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return (xtile, ytile)

def draw_map(my_map, file_name, tile_url, zoom=12):
    """Draw map to SVG"""
    extremes = my_map.get_geo_real()
    upper_left = deg2num(extremes[0], extremes[1], zoom)
    lower_right = deg2num(extremes[2], extremes[3], zoom)
    top = ET.Element('svg', {'width': str((lower_right[0] - upper_left[0] + 1) * 256),
                             'height': str((lower_right[1] - upper_left[1] + 1) * 256),
                             'xmlns': 'http://www.w3.org/2000/svg'})
    for tile_x in range(upper_left[0], lower_right[0] + 1):
        for tile_y in range(upper_left[1], lower_right[1] + 1):
            ET.SubElement(top, 'image', {'href': tile_url.format(z=zoom, x=tile_x, y=tile_y),
                                         'height': "256",
                                         'width': "256",
                                         'x': str((tile_x - upper_left[0]) * 256),
                                         'y': str((tile_y - upper_left[1]) * 256)})
    tree = ET.ElementTree(element=top)
    ET.indent(tree)
    tree.write(file_name)
