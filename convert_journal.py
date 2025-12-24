import json
import shutil
from pathlib import Path

from PIL import Image
import pillow_heif
from bs4 import BeautifulSoup

import re

# Enable HEIC support
pillow_heif.register_heif_opener()

SRC_DIR = Path(".").resolve()
DST_DIR = SRC_DIR.parent / "Journal_PNG"

ENTRIES_DIR = DST_DIR / "Entries"
RESOURCES_DIR = DST_DIR / "Resources"


# -------------------------------------------------
# 1. Copy full export to new directory
# -------------------------------------------------
def copy_export():
    if DST_DIR.exists():
        print(f"{DST_DIR} already exists – using existing copy.")
        return

    print(f"Copying export to {DST_DIR}")
    shutil.copytree(SRC_DIR, DST_DIR)


# -------------------------------------------------
# 2. Convert HEIC -> PNG (inside new dir only)
# -------------------------------------------------
def convert_heic_to_png():
    for heic_file in RESOURCES_DIR.glob("*.heic"):
        png_file = heic_file.with_suffix(".png")

        if png_file.exists():
            continue

        print(f"Converting {heic_file.name}")
        with Image.open(heic_file) as img:
            img.save(png_file, format="PNG")


# -------------------------------------------------
# 3. Build Leaflet map snippet
# -------------------------------------------------
def build_map_html(visits, map_id):
    markers = []
    bounds = []

    for v in visits:
        lat = v["latitude"]
        lon = v["longitude"]
        name = v.get("placeName", "")
        city = v.get("city", "")
        popup = f"{name} ({city})".replace('"', "'")

        markers.append(f'L.marker([{lat}, {lon}]).addTo(map).bindPopup("{popup}");')
        bounds.append(f"[{lat}, {lon}]")

    return f"""
<div id="{map_id}" style="height: 600px; width: 50%; margin: 2em;"></div>

<link
  rel="stylesheet"
  href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>

<script>
  var map = L.map('{map_id}');
  L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap contributors'
  }}).addTo(map);

  var bounds = L.latLngBounds([{",".join(bounds)}]);
  map.fitBounds(bounds);

  {''.join(markers)}
</script>
"""


# -------------------------------------------------
# 4. Process entry HTML files
# -------------------------------------------------
def process_entries():
    for entry_file in ENTRIES_DIR.glob("*.html"):
        print(f"Updating {entry_file.name}")

        soup = BeautifulSoup(entry_file.read_text(encoding="utf-8"), "html.parser")

        visits = []

        # -----------------------------------------
        # Find images and related JSON files
        # -----------------------------------------
        for img in soup.find_all("img"):
            src = img.get("src", "")

            if not src.lower().endswith(".heic"):
                continue

            # Replace image with PNG
            img["src"] = src[:-5] + ".png"

            # Extract UUID filename
            filename = Path(src).name  # UUID.heic
            json_name = filename.replace(".heic", ".json")
            json_path = RESOURCES_DIR / json_name

            if not json_path.exists():
                continue

            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
                visits.extend(data.get("visits", []))
            except Exception as e:
                print(f"  ⚠️ Failed to read {json_name}: {e}")

        # -----------------------------------------
        # Inject map if we have locations
        # -----------------------------------------
        if visits:
            map_id = f"map_{entry_file.stem}"
            markers_js = []
            bounds_js = []

            for v in visits:
                lat = v["latitude"]
                lon = v["longitude"]
                name = v.get("placeName", "")
                city = v.get("city", "")
                popup = f"<b>{name}</b><br><i>{city}</i>".replace('"', "'")
                markers_js.append(
                    f'L.marker([{lat},{lon}]).addTo(map).bindPopup("{popup}");'
                )
                bounds_js.append(f"[{lat},{lon}]")

            map_html = f"""
<div id="{map_id}" style="height: 400px; margin: 2em 0;"></div>
<link href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" rel="stylesheet"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
var map = L.map('{map_id}');
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap contributors'
}}).addTo(map);

var bounds = L.latLngBounds([{','.join(bounds_js)}]);
map.fitBounds(bounds);

{''.join(markers_js)}
</script>
"""
            if soup.body:
                soup.body.append(BeautifulSoup(map_html, "html.parser"))

        # -----------------------------------------
        # Add consistent CSS style
        # -----------------------------------------
        style_tag = soup.new_tag("style")
        style_tag.string = """
body {
    font-family: Arial, sans-serif;
    background-color: #f8f9fa;
    margin: 20px;
    line-height: 1.5em;
}
h1, .pageHeader, .title {
    color: #2c3e50;
    font-weight: bold;
}
.entry-container {
    max-width: 900px;
    margin: auto;
    padding: 1.5em;
    background-color: #ffffff;
    border-radius: 12px;
    box-shadow: 0 2px 12px rgba(0,0,0,0.1);
}
.assetGrid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
    gap: 8px;
    margin: 1em 0;
}
.gridItem {
    border-radius: 8px;
    overflow: hidden;
    box-shadow: 0 1px 5px rgba(0,0,0,0.1);
}
.gridItem img {
    width: 100%;
    height: 100%;
    object-fit: cover;
}
.bodyText, p {
    margin: 0.5em 0;
    font-size: 14px;
}
.p3 {
    display: none;
}
.entry-links .p2 {
    display: none;
}
#map_{map_id} {{
    border-radius: 12px;
    box-shadow: 0 2px 12px rgba(0,0,0,0.2);
}}
"""
        if soup.head:
            soup.head.append(style_tag)

        # Wrap content in container div
        body_children = list(soup.body.children)
        wrapper = soup.new_tag("div", **{"class": "entry-container"})

        for child in body_children:
            wrapper.append(child.extract())
        soup.body.insert(0, wrapper)

        # Adjust the first image to be larger if it's the main map/image
        first_grid = soup.select_one("div.assetGrid")
        if first_grid:
            first_item = first_grid.find("div", class_="gridItem")
            if first_item:
                first_item["style"] = (
                    "grid-column: span 2; grid-row: span 2; height: 250px;"
                )
                first_img = first_item.find("img")
                if first_img:
                    first_img["style"] = "object-fit: cover; width: 100%; height: 100%;"

        entry_file.write_text(str(soup), encoding="utf-8")
        print(f"{entry_file.name} styled successfully")


def update_index_map_clickable():
    index_file = DST_DIR / "index.html"
    if not index_file.exists():
        print("index.html not found, skipping full trip map.")
        return

    soup = BeautifulSoup(index_file.read_text(encoding="utf-8"), "html.parser")

    all_visits = []

    # Predefined marker colors
    colors = [
        "red",
        "blue",
        "green",
        "orange",
        "purple",
        "darkred",
        "cadetblue",
        "darkgreen",
        "darkblue",
        "magenta",
        "lime",
        "orangered",
        "lightgray",
        "beige",
        "black",
    ]

    # Assign a color per day
    date_to_color = {}
    date_list = []

    for entry_file in sorted(ENTRIES_DIR.glob("*.html")):
        date_str = entry_file.stem.split("_")[0]
        if date_str not in date_to_color:
            color = colors[len(date_to_color) % len(colors)]
            date_to_color[date_str] = color
            date_list.append(date_str)
        color = date_to_color[date_str]

        entry_soup = BeautifulSoup(
            entry_file.read_text(encoding="utf-8"), "html.parser"
        )
        for img in entry_soup.find_all("img"):
            src = img.get("src", "")
            if not src.lower().endswith(".png"):
                continue
            filename = Path(src).name.replace(".png", ".json")
            json_path = RESOURCES_DIR / filename
            if json_path.exists():
                try:
                    data = json.loads(json_path.read_text(encoding="utf-8"))
                    for visit in data.get("visits", []):
                        visit["_color"] = color
                        visit["_date"] = date_str
                        all_visits.append(visit)
                except Exception as e:
                    print(f"Failed to read {filename}: {e}")

    if not all_visits:
        print("No visits found, skipping full trip map.")
        return

    markers_js = []
    bounds_js = []

    for v in all_visits:
        lat = v["latitude"]
        lon = v["longitude"]
        name = v.get("placeName", "")
        city = v.get("city", "")
        color = v.get("_color", "blue")
        popup = f"<b>{name}</b><br><i>{city}</i>".replace('"', "'")

        markers_js.append(
            f"""var marker = L.circleMarker([{lat},{lon}], {{color:'{color}', radius:8}});
marker.addTo(map).bindPopup("{popup}");
marker._day_color = "{color}";
markers.push(marker);"""
        )
        bounds_js.append(f"[{lat}, {lon}]")

    legend_html = "<div class='legend' style='margin-bottom:10px;'><b>Click a day to filter markers:</b><br>"
    for i, date_str in enumerate(date_list, start=1):
        color = date_to_color[date_str]
        legend_html += f"""
        <span style='background:{color};width:16px;height:16px;display:inline-block;margin-right:6px;border-radius:50%;vertical-align:middle;' onclick='toggleMarkers("{color}")'></span>
        <span onclick='toggleMarkers("{color}")' style='text-decoration: underline; margin-right: 15px;'>{date_str}</span>
        """
    legend_html += "</div>"

    map_html = f"""
<div id="map_full_trip" style="height: 500px; margin-top: 2em;"></div>
{legend_html}
<link href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" rel="stylesheet"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
var map = L.map('map_full_trip');
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap contributors'
}}).addTo(map);

var markers = [];
var bounds_all = L.latLngBounds([{','.join(bounds_js)}]);
map.fitBounds(bounds_all);

{''.join(markers_js)}

// Function to show/hide markers by color and zoom to fit
var activeColor = null;
function toggleMarkers(color) {{
    var visibleMarkers = [];
    if(activeColor === color) {{
        // Show all markers
        markers.forEach(m => {{
            map.addLayer(m);
            visibleMarkers.push(m);
        }});
        activeColor = null;
    }} else {{
        markers.forEach(m => {{
            if(m._day_color === color) {{
                map.addLayer(m);
                visibleMarkers.push(m);
            }} else {{
                map.removeLayer(m);
            }}
        }});
        activeColor = color;
    }}
    if(visibleMarkers.length > 0){{
        var group = L.featureGroup(visibleMarkers);
        map.fitBounds(group.getBounds().pad(0.1));
    }}
}}
</script>
"""

    soup.body.append(BeautifulSoup(map_html, "html.parser"))
    index_file.write_text(str(soup), encoding="utf-8")
    print("Full trip map updated with auto-zoom for visible markers")


def beautify_index_html():
    index_file = DST_DIR / "index.html"
    if not index_file.exists():
        return

    soup = BeautifulSoup(index_file.read_text(encoding="utf-8"), "html.parser")

    # Add viewport meta tag for mobile
    if not soup.find("meta", attrs={"name": "viewport"}):
        meta_tag = soup.new_tag("meta")
        meta_tag.attrs["name"] = "viewport"
        meta_tag.attrs["content"] = (
            "width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no"
        )
        soup.head.insert(0, meta_tag)

    # Add CSS styles
    style_tag = soup.new_tag("style")
    style_tag.string = """
body {
    font-family: Arial, sans-serif;
    background-color: #f8f9fa;
    margin: 10px;
    font-size: 16px;
}
h1 {
    text-align: center;
    color: #2c3e50;
    margin-bottom: 1em;
}
.entry-links {
    width: 95%;
    max-width: 1000px;
    margin: auto;
    padding: 1em;
    background-color: #ffffff;
    border-radius: 12px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
}
.entry-links p {
    margin: 0.5em 0;
    font-size: 16px;
}
#map_full_trip {
    width: 100%;
    max-height: 600px;
    height: 400px;
    margin: 2em auto;
    border-radius: 12px;
    box-shadow: 0 2px 12px rgba(0,0,0,0.2);
}
.leaflet-popup-content {
    font-size: 14px;
}
.legend {
    background: white;
    padding: 10px;
    border-radius: 8px;
    box-shadow: 0 1px 5px rgba(0,0,0,0.3);
    line-height: 1.5em;
    cursor: pointer;
}
.legend span {
    display:inline-block;
    width:12px;
    height:12px;
    margin-right: 6px;
    border-radius: 50%;
}

/* Responsive for small screens */
@media (max-width: 600px) {
    .entry-links {
        padding: 0.5em;
    }
    #map_full_trip {
        height: 300px;
    }
    .entry-links p {
        font-size: 14px;
    }
}
"""
    soup.head.append(style_tag)

    # Wrap all paragraphs and divs in .entry-links container
    body_children = list(soup.body.children)
    wrapper = soup.new_tag("div", **{"class": "entry-links"})
    for child in body_children:
        if child.name in ["p", "div"]:
            wrapper.append(child.extract())
    soup.body.insert(0, wrapper)

    # Remove empty <p>
    for p in soup.find_all("p"):
        if not p.get_text(strip=True):
            p.decompose()

    index_file.write_text(str(soup), encoding="utf-8")
    print("Index.html beautified and mobile responsive")


def clean_empty_paragraphs_index():
    index_file = DST_DIR / "index.html"
    if not index_file.exists():
        return

    soup = BeautifulSoup(index_file.read_text(encoding="utf-8"), "html.parser")
    for p in soup.find_all("p"):
        if not p.get_text(strip=True):
            p.decompose()
    index_file.write_text(str(soup), encoding="utf-8")
    print("Removed empty <p> elements from index.html")


def clean_empty_paragraphs_entries():
    for entry_file in ENTRIES_DIR.glob("*.html"):
        soup = BeautifulSoup(entry_file.read_text(encoding="utf-8"), "html.parser")
        for p in soup.find_all("p"):
            if not p.get_text(strip=True):
                p.decompose()
        entry_file.write_text(str(soup), encoding="utf-8")
    print("Removed empty <p> elements from all entry pages")


def add_responsive_viewport(soup):
    # Add viewport meta if not present
    if not soup.find("meta", attrs={"name": "viewport"}):
        meta_tag = soup.new_tag("meta")
        meta_tag.attrs["name"] = "viewport"
        meta_tag.attrs["content"] = (
            "width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no"
        )
        soup.head.insert(0, meta_tag)


def beautify_entries():
    for entry_file in ENTRIES_DIR.glob("*.html"):
        soup = BeautifulSoup(entry_file.read_text(encoding="utf-8"), "html.parser")
        add_responsive_viewport(soup)

        # Add mobile-friendly CSS
        style_tag = soup.new_tag("style")
        style_tag.string = """
        body {
            font-family: Arial, sans-serif;
            font-size: 16px;
            background-color: #f8f9fa;
            margin: 10px;
            line-height: 1.5em;
        }
        .container, .entry-container {
            width: 95%;
            max-width: 1000px;
            margin: auto;
            padding: 10px;
            background-color: #ffffff;
            border-radius: 12px;
            box-shadow: 0 2px 12px rgba(0,0,0,0.1);
        }
        .gridItem {
            margin-bottom: 16px;
        }
        .gridItem img, img.asset_image {
            width: 100%;
            height: auto;
            object-fit: contain; /* Show full image */
            display: block;
            border-radius: 8px;
        }
        .bodyText, p {
            margin: 0.5em 0;
            font-size: 14px;
        }
        #map_full_trip, .entryMap {
            width: 100%;
            max-height: 600px;
            height: 400px;
            margin: 1em auto;
            border-radius: 12px;
            box-shadow: 0 2px 12px rgba(0,0,0,0.2);
        }
        @media (max-width: 600px) {
            .assetGrid {
                display: flex !important;
            }
            .gridItem img, img.asset_image {
                width: 100%;
                height: auto;
            }
            #map_full_trip, .entryMap {
                height: 300px;
            }
            .asset_image {
                object-fit: contain !important;
            }
        }
        """
        soup.head.append(style_tag)
        entry_file.write_text(str(soup), encoding="utf-8")


# -------------------------------------------------
# Main
# -------------------------------------------------
if __name__ == "__main__":
    copy_export()
    convert_heic_to_png()
    process_entries()
    update_index_map_clickable()
    beautify_index_html()
    clean_empty_paragraphs_index()
    clean_empty_paragraphs_entries()
    beautify_entries()
    print("Finished. New version is in Journal_PNG/")
