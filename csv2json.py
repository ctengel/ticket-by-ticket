#!/usr/bin/env python3
"""Non-importable script to convert CSV to JSON"""

import sys
from tkt_by_tkt import editor

editor.gmcsv2tbtjson(sys.argv[1], sys.argv[2])
