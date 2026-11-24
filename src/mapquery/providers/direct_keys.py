"""The front-end keys of the direct channel.

These keys were found in the providers' own public JavaScript bundles. They
are shared with the providers' live websites, so they are rate limited and can
be busy. A user who needs steady service sets their own key in the
environment and the tool switches to the official channel.
"""

# The Amap front-end key. It works on https://www.amap.com/_AMapService/v3/.
AMAP_FRONTEND_KEY = "2f282f369e388ef01bae260cbc35edce"

# The Baidu AK that Baidu ships in its own public page bundle. It is
# accepted by the documented WebService API, so the direct channel of Baidu
# uses it for the search, the geocode, the reverse geocode and the detail.
# It is shared with the live site of Baidu, so it is rate limited, and its
# routing service is switched off.
BAIDU_FRONTEND_AK = "8z3RxyDq3sseF20zMZcBxkzhfTdAeSq7"

# The Tencent front-end key. It works on https://apis.map.qq.com/ws/.
TENCENT_FRONTEND_KEY = "4VQBZ-ZGO3G-VGSQE-ILN4G-LWFUK-5WB7H"
