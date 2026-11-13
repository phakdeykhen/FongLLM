"""
The 260 design types FongAI knows: exact canvas size (pixels, at most 2400 on the long side; print sizes keep
their real proportions) and which layout makes them. FongAI looks the type up here instead of guessing.

Layouts:
  banner    wide: text on the left, photo on the right              (web banners, covers, billboards, backdrops)
  thumb     wide with a huge 2-4 word headline                      (YouTube thumbnail)
  square    photo behind, text at the bottom                        (Instagram / Facebook posts, social graphics)
  poster    portrait: photo on top, text below                      (posters, flyers, stories, covers)
  tall      very tall: brand on top, photo in the middle, text below (roll-ups, standees, feather flags)
  repeat    the brand name tiled in a grid                          (step and repeat, media and sponsor walls)
  doc:pdf / doc:docx / doc:pptx   a real document from the file maker (brochures, profiles, decks)
  logo      a single icon from the image model
  soon:...  not built yet: cards, certificates, infographics, carousels, packaging and other flat artwork
"""
import re

# name | layout | width x height | other names people use (comma separated)
TABLE = """
Website Banner | banner | 1920x600 | web banner, site banner
Website Hero Banner | banner | 1920x1080 | hero banner, hero image, landing page banner, header image
Facebook Cover Banner | banner | 1640x624 | facebook cover, fb cover, facebook page cover
Facebook Ads Banner | square | 1080x1080 | facebook ad, fb ad, facebook ads, meta ad, meta ads
Instagram Post | square | 1080x1350 | ig post, insta post, instagram feed post
Instagram Story | poster | 1080x1920 | ig story, insta story, instagram stories
Instagram Reel Cover | poster | 1080x1920 | reel cover, reels cover, ig reel cover
TikTok Video Cover | poster | 1080x1920 | tiktok cover, tik tok cover
YouTube Channel Banner | banner | 2400x1350 | youtube banner, yt banner, youtube channel art banner
YouTube Thumbnail | thumb | 1280x720 | yt thumbnail, video thumbnail, thumbnail
Google Display Ads Banner | banner | 1200x628 | google ad, google ads banner, display ad, google display ad
LinkedIn Banner | banner | 1584x396 | linkedin cover, linkedin background
Email Marketing Banner | banner | 1200x400 | email banner, newsletter banner, email header
App Promotion Banner | banner | 1200x628 | app banner, app promo banner, app ad
Promotional Web Popup | square | 800x800 | web popup, popup, pop-up
E-commerce Store Banner | banner | 1920x600 | ecommerce banner, online store banner, shop banner, shopee banner, lazada banner
Sale Promotion Banner | banner | 1600x900 | sale banner, promotion banner, promo banner, discount banner
Product Launch Banner | banner | 1600x900 | launch banner, new product banner
Billboard Banner | banner | 2400x700 | billboard
Large Outdoor Banner | banner | 2400x800 | outdoor banner, vinyl banner
Roll-up Banner | tall | 1020x2400 | roll up banner, rollup banner, roll-up, roll up, rollup
X-Banner Stand | tall | 900x2400 | x banner, x-banner, x stand
L-Banner Stand | tall | 960x2400 | l banner, l-banner
Y-Banner Stand | tall | 1067x2400 | y banner, y-banner
Pull-up Banner | tall | 1020x2400 | pull up banner, pullup banner
Hanging Banner | tall | 800x2400 | hanging sign banner
Street Banner | tall | 800x2400 | pole banner, lamp post banner
Building Banner | tall | 1200x2400 | building wrap banner
Fence Banner | banner | 2400x800 | fence mesh banner
Shop Front Banner | banner | 2400x600 | shopfront banner, shop sign banner, storefront banner, shop signboard
Roadside Advertising Banner | banner | 2400x800 | roadside banner, roadside ad
LED Screen Advertising | banner | 1920x1080 | led screen, led screen ad, led display ad
Bus Advertising Design | banner | 2400x700 | bus ad, bus advertising, bus banner
Vehicle Wrap Design | soon:artwork | 2400x1000 | vehicle wrap, car wrap
Car Sticker Advertising | banner | 1800x600 | car sticker
Wall Advertising Graphics | banner | 2400x1350 | wall graphics, wall advertising, wall mural ad
Feather Flag | tall | 600x2400 | feather banner, feather flag banner
Teardrop Flag | tall | 873x2400 | teardrop banner
Rectangle Flag | banner | 1800x1200 | rectangle flag, rectangular flag
Beach Flag | tall | 600x2400 | beach banner
Advertising Flag | banner | 1800x1200 | ad flag, advertising flag
Company Flag | banner | 1800x1200 | corporate flag, business flag
National Flag | soon:artwork | 1800x1200 | country flag
Event Flag | banner | 1800x1200 | event flags
Table Flag | banner | 1800x1200 | desk flag
Handheld Flag | banner | 1800x1200 | hand flag, hand-held flag
Car Flag | banner | 1800x1200 | car window flag
Garden Flag | poster | 1600x2400 | yard flag
Custom Promotional Flag | banner | 1800x1200 | promotional flag, promo flag, custom flag
Vertical Pole Flag | tall | 800x2400 | vertical flag, pole flag
Horizontal Flag | banner | 1800x1200 | horizontal banner flag
Photo Booth Backdrop | banner | 2400x1600 | photobooth backdrop, photo backdrop, photo wall
Wedding Backdrop | banner | 2400x1600 | wedding background, wedding stage backdrop
Birthday Backdrop | banner | 2400x1600 | birthday background, birthday party backdrop
Graduation Backdrop | banner | 2400x1600 | graduation background
Corporate Event Backdrop | banner | 2400x1600 | company event backdrop, corporate backdrop
Exhibition Backdrop | banner | 2400x1600 | expo backdrop
Conference Backdrop | banner | 2400x1600 | seminar backdrop, conference background
Press Conference Backdrop | repeat | 2400x1600 | press backdrop, press wall
Step and Repeat Banner | repeat | 2400x1600 | step and repeat, step & repeat, step-and-repeat
Red Carpet Backdrop | repeat | 2400x1600 | red carpet
Media Wall | repeat | 2400x1600 | media backdrop, interview wall
Sponsor Wall | repeat | 2400x1600 | sponsor backdrop, sponsors wall
Event Stage Background | banner | 2400x1000 | stage background, stage backdrop, stage banner
Event Welcome Board | poster | 1600x2400 | welcome board, welcome sign board
Event Entrance Standee | tall | 1020x2400 | entrance standee, event standee, standee
Wedding Welcome Sign | poster | 1600x2400 | wedding sign, wedding welcome board
Birthday Welcome Sign | poster | 1600x2400 | birthday sign, birthday welcome board
Event Direction Sign | soon:sign | 1800x1200 | direction sign, directional sign, wayfinding sign
Photo Frame Design | soon:frame | 2400x1600 | photo frame
Photo Booth Props | soon:artwork | 2400x2400 | booth props, photo props
Selfie Frame | soon:frame | 1600x2400 | selfie board, instagram frame board
Party Decoration Banner | banner | 2400x800 | party banner, bunting banner, happy birthday banner
Business Poster | poster | 1697x2400 | company poster, corporate poster
Promotional Poster | poster | 1697x2400 | promotion poster, promo poster
Product Poster | poster | 1697x2400 | product promotion poster
Sale Poster | poster | 1697x2400 | sales poster
Discount Poster | poster | 1697x2400 | discount flyer poster
Restaurant Poster | poster | 1697x2400 | cafe poster, coffee shop poster
Food Poster | poster | 1697x2400 | food promotion poster
Beverage Poster | poster | 1697x2400 | drink poster, drinks poster, coffee poster, juice poster
Fashion Poster | poster | 1697x2400 | clothing poster, clothes poster
Beauty Poster | poster | 1697x2400 | skincare poster, cosmetics poster, makeup poster
Salon Poster | poster | 1697x2400 | spa poster, barber poster, hair salon poster, nail salon poster
Technology Poster | poster | 1697x2400 | tech poster, it poster, ai poster
Education Poster | poster | 1697x2400 | school poster, course poster, class poster, training course poster
Real Estate Poster | poster | 1697x2400 | property poster, house for sale poster, condo poster
Property Advertisement Poster | poster | 1697x2400 | property ad, real estate ad, land for sale
Hotel Poster | poster | 1697x2400 | resort poster
Travel Poster | poster | 1697x2400 | trip poster, travel agency poster
Tourism Poster | poster | 1697x2400 | tourism, visit cambodia poster
Event Poster | poster | 1697x2400 | event flyer poster
Concert Poster | poster | 1697x2400 | live music poster, show poster
Movie Poster | poster | 1620x2400 | film poster
Sports Poster | poster | 1697x2400 | football poster, tournament poster, gym poster, fitness poster
Music Poster | poster | 1697x2400 | album poster, band poster
Recruitment Poster | poster | 1697x2400 | hiring poster, we are hiring, job poster, job vacancy poster
Health Awareness Poster | poster | 1697x2400 | health poster, medical poster, clinic poster
Public Awareness Poster | poster | 1697x2400 | awareness poster, campaign poster
Political Campaign Poster | poster | 1697x2400 | election poster
Flyer | poster | 1697x2400 | flyers, flier
Leaflet | poster | 1697x2400 | leaflets
Brochure | doc:pdf | 0x0 | brochures
Tri-fold Brochure | doc:pdf | 0x0 | trifold brochure, tri fold brochure, trifold
Bi-fold Brochure | doc:pdf | 0x0 | bifold brochure, bi fold brochure
Company Profile | doc:pdf | 0x0 | business profile, company profile document
Product Catalog | doc:pdf | 0x0 | product catalogue, catalog, catalogue
Service Catalog | doc:pdf | 0x0 | service catalogue, services list
Magazine Cover | poster | 1855x2400 | magazine front cover
Magazine Layout | doc:pdf | 0x0 | magazine page, magazine article layout
Newspaper Advertisement | poster | 1697x2400 | newspaper ad, print ad
Invitation Card | soon:card | 1714x2400 | invitation, invite card, invite
Wedding Invitation | soon:card | 1714x2400 | wedding invite, wedding card
Birthday Invitation | soon:card | 1714x2400 | birthday invite, party invitation
Graduation Invitation | soon:card | 1714x2400 | graduation invite
Business Card | soon:card | 1050x600 | business cards, visiting card
Name Card | soon:card | 1050x600 | name cards
Letterhead | doc:docx | 0x0 | letter head, company letterhead
Envelope Design | soon:artwork | 2200x1100 | envelope
Certificate Design | soon:certificate | 2400x1697 | certificate, certificate of completion, award certificate
Menu Design | doc:pdf | 0x0 | menu
Price List | doc:pdf | 0x0 | pricelist, price sheet
Restaurant Menu | doc:pdf | 0x0 | food menu, cafe menu, coffee menu, drink menu
Voucher Design | soon:card | 2100x900 | voucher, gift voucher
Coupon Design | soon:card | 2100x900 | coupon, discount coupon
Gift Card | soon:card | 1011x638 | giftcard
Thank You Card | soon:card | 1714x2400 | thank-you card, thanks card
Greeting Card | soon:card | 1714x2400 | greeting cards, holiday card
Company Logo | logo | 1024x1024 | logo, brand logo, business logo
Brand Identity | doc:pdf | 0x0 | branding, brand kit, visual identity
Brand Guidelines | doc:pdf | 0x0 | brand guideline, brand book, style guide
Business Stationery | doc:pdf | 0x0 | stationery, stationery set
Business Presentation | doc:pptx | 0x0 | company presentation, business slides
Company Portfolio | doc:pdf | 0x0 | business portfolio
Corporate Identity | doc:pdf | 0x0 | corporate identity design, ci design
Email Signature | soon:card | 1200x400 | e-mail signature
Staff ID Card | soon:card | 638x1011 | id card, staff card, employee id card
Employee Badge | soon:card | 638x1011 | badge, name badge, staff badge
Company Uniform | soon:artwork | 2400x2400 | uniform design
T-shirt Design | soon:artwork | 2400x2400 | tshirt design, t shirt design, shirt design, tee design
Polo Shirt Design | soon:artwork | 2400x2400 | polo design, polo shirt
Cap Design | soon:artwork | 2400x1200 | hat design, cap
Uniform Printing | soon:artwork | 2400x2400 | uniform print
Office Signage | soon:sign | 2400x800 | office sign
Store Signage | banner | 2400x800 | store sign, shop sign
Reception Sign | soon:sign | 2400x800 | reception wall sign, lobby sign
Door Sign | soon:sign | 800x1200 | door plate
Directional Signage | soon:sign | 1800x1200 | wayfinding signage, arrow sign
Product Packaging | soon:artwork | 2400x1800 | packaging, package design, packaging design
Product Label | soon:artwork | 2400x900 | label design, product sticker label
Bottle Label | soon:artwork | 2400x900 | bottle sticker
Food Packaging | soon:artwork | 2400x1800 | food box, food package
Beverage Packaging | soon:artwork | 2400x1800 | drink packaging, cup design
Cosmetic Packaging | soon:artwork | 2400x1800 | cosmetics box, skincare packaging
Box Packaging | soon:artwork | 2400x1800 | box design
Shopping Bag Design | soon:artwork | 1800x2400 | shopping bag, tote bag design
Paper Bag Design | soon:artwork | 1800x2400 | paper bag
Product Mockup | soon:artwork | 2400x1800 | mockup, mock-up
Product Advertisement | square | 1080x1350 | product ad, product advert
Product Showcase | square | 1080x1350 | product display post
Product Promotion | square | 1080x1350 | product promo
Product Comparison Graphic | soon:infographic | 1080x1350 | comparison graphic, product comparison
Product Feature Graphic | soon:infographic | 1080x1350 | feature graphic, product features
Product Instruction Sheet | doc:pdf | 0x0 | instruction sheet, user guide, manual
Packaging Sticker | square | 1200x1200 | sticker, packaging seal sticker
Barcode Label | soon:artwork | 1200x600 | barcode
Shipping Label | soon:card | 1200x1800 | delivery label, parcel label
Facebook Post | square | 1080x1080 | fb post, facebook graphic
Facebook Story | poster | 1080x1920 | fb story
Facebook Carousel | soon:carousel | 1080x1080 | fb carousel
Instagram Carousel | soon:carousel | 1080x1350 | ig carousel, insta carousel, carousel post
Instagram Highlight Cover | soon:icon | 1080x1920 | highlight cover, ig highlight
TikTok Post Graphic | poster | 1080x1920 | tiktok post, tiktok graphic, tik tok post
YouTube End Screen | banner | 1920x1080 | end screen, outro screen
YouTube Channel Art | banner | 2400x1350 | channel art
Social Media Infographic | soon:infographic | 1080x1350 | social infographic
Quote Graphic | square | 1080x1080 | quote post, quote image, quotes
Motivational Post | square | 1080x1080 | motivation post, inspirational post
Announcement Post | square | 1080x1080 | announcement, announcement graphic
News Update Graphic | square | 1080x1080 | news post, news update
Testimonial Graphic | square | 1080x1080 | testimonial, testimonial post
Customer Review Graphic | square | 1080x1080 | review post, customer review, customer feedback post
Giveaway Post | square | 1080x1080 | giveaway
Contest Announcement | square | 1080x1080 | contest post, competition post
Countdown Post | square | 1080x1080 | countdown
Holiday Greeting Post | square | 1080x1080 | holiday post, greeting post, festive post
New Year Poster | poster | 1697x2400 | happy new year poster, new year
Christmas Poster | poster | 1697x2400 | christmas, xmas poster
Valentine's Day Poster | poster | 1697x2400 | valentine poster, valentines poster, valentine
Halloween Poster | poster | 1697x2400 | halloween
Easter Poster | poster | 1697x2400 | easter
Black Friday Poster | poster | 1697x2400 | black friday
Cyber Monday Banner | banner | 1600x900 | cyber monday
Mother's Day Poster | poster | 1697x2400 | mothers day, mother's day
Father's Day Poster | poster | 1697x2400 | fathers day, father's day
International Women's Day Poster | poster | 1697x2400 | women's day, womens day
Khmer New Year Poster | poster | 1697x2400 | khmer new year, choul chnam thmey, ចូលឆ្នាំខ្មែរ
Pchum Ben Poster | poster | 1697x2400 | pchum ben, ភ្ជុំបិណ្ឌ
Water Festival Poster | poster | 1697x2400 | water festival, bon om touk, ពិធីបុណ្យអុំទូក
Chinese New Year Poster | poster | 1697x2400 | chinese new year, lunar new year
Ramadan Greeting Design | square | 1080x1080 | ramadan, eid greeting, eid mubarak
Wedding Anniversary Poster | poster | 1697x2400 | anniversary poster
Grand Opening Poster | poster | 1697x2400 | grand opening, opening soon, soft opening
Store Anniversary Poster | poster | 1697x2400 | shop anniversary
Graduation Celebration Poster | poster | 1697x2400 | graduation poster, congratulations graduate
Business Infographic | soon:infographic | 1697x2400 | infographic, infographics
Educational Infographic | soon:infographic | 1697x2400 | education infographic
Process Infographic | soon:infographic | 1697x2400 | process graphic, steps infographic
Timeline Infographic | soon:infographic | 2400x1350 | timeline
Statistics Infographic | soon:infographic | 1697x2400 | stats infographic
Comparison Infographic | soon:infographic | 1697x2400 | versus infographic, vs infographic
Organizational Chart | soon:infographic | 2400x1350 | org chart, organisation chart, organization chart
Workflow Diagram | soon:infographic | 2400x1350 | workflow, flow chart, flowchart
Product Feature Infographic | soon:infographic | 1697x2400 | feature infographic
Company Structure Chart | soon:infographic | 2400x1350 | company structure
Instructional Poster | poster | 1697x2400 | how-to poster, instruction poster
Safety Poster | poster | 1697x2400 | safety sign poster, warning poster
Training Poster | poster | 1697x2400 | workshop poster
Data Visualization | soon:infographic | 2400x1350 | data visualisation, chart design, dashboard graphic
Technical Diagram | soon:infographic | 2400x1350 | diagram, technical drawing
Exhibition Booth Design | soon:artwork | 2400x1350 | booth design, exhibition booth, expo booth
Trade Show Backdrop | banner | 2400x1600 | trade show background, tradeshow backdrop
Exhibition Standee | tall | 1020x2400 | expo standee
Exhibition Counter Design | soon:artwork | 2400x1200 | exhibition counter, booth counter
Promotional Counter | soon:artwork | 2400x1200 | promo counter, promotion table, sampling counter
Display Stand Design | tall | 1020x2400 | display stand
Product Display Board | poster | 1600x2400 | display board
Exhibition Wall Graphics | banner | 2400x1350 | exhibition wall
Conference Booth Graphics | banner | 2400x1350 | conference booth
Sponsor Display Board | repeat | 2400x1600 | sponsor board, sponsors board
Event Registration Desk Design | banner | 2400x800 | registration desk, check-in desk
Promotional Tablecloth | soon:artwork | 2400x1350 | tablecloth, table cover
Hanging Exhibition Sign | banner | 2400x600 | hanging sign, ceiling sign
Booth Header Banner | banner | 2400x500 | booth header, fascia banner
Store Promotion Poster | poster | 1697x2400 | in-store poster, shop promotion poster
Window Display Graphics | banner | 2400x1350 | window graphics, window sticker, window display
Shelf Talker | soon:card | 1200x400 | shelf tag, shelf strip
Price Tag Design | soon:card | 600x900 | price tag, price label
Product Display Card | poster | 1200x1800 | display card, tent card, table tent
POS Counter Display | poster | 1200x1800 | pos display, counter display, point of sale display
Wobbler Design | square | 1200x1200 | wobbler, shelf wobbler
Promotional Sticker | square | 1200x1200 | promo sticker, sale sticker
Sale Standee | tall | 1020x2400 | sale stand, promotion standee
Shopping Mall Banner | tall | 800x2400 | mall banner, mall hanging banner
In-store Advertising | poster | 1697x2400 | in store ad, in-store ad
Checkout Counter Sign | banner | 1800x600 | checkout sign, cashier sign
Menu Board | banner | 1920x1080 | menu board design, drinks board
Digital Signage | banner | 1920x1080 | digital sign, tv screen ad, screen ad
PowerPoint Presentation | doc:pptx | 0x0 | powerpoint, presentation, slides, slide deck
Pitch Deck | doc:pptx | 0x0 | investor deck, startup pitch, pitch
Business Proposal Design | doc:docx | 0x0 | business proposal, proposal
Company Profile Presentation | doc:pptx | 0x0 | company profile slides, company profile deck
Training Slides | doc:pptx | 0x0 | training deck, training presentation
Webinar Presentation | doc:pptx | 0x0 | webinar slides, webinar deck
Infographic Slides | doc:pptx | 0x0 | infographic deck
Dashboard Presentation | doc:pptx | 0x0 | dashboard slides, kpi slides
E-book Cover | poster | 1600x2560 | ebook cover, book cover, kindle cover
PDF Brochure | doc:pdf | 0x0 | brochure pdf
Digital Report | doc:pdf | 0x0 | report, annual report, e-report
Portfolio Presentation | doc:pptx | 0x0 | portfolio deck, portfolio slides
"""


def _norm(s):
    s = s.lower().replace("&", " and ").replace("’", "'")
    s = re.sub(r"[^\w\s'ក-៿]", " ", s)   # keep Khmer letters
    return re.sub(r"\s+", " ", s).strip()


def _parse():
    out = []
    for line in TABLE.strip().splitlines():
        name, layout, size, aliases = [x.strip() for x in line.split("|")]
        w, h = (int(v) for v in size.split("x"))
        names = [name] + [a.strip() for a in aliases.split(",") if a.strip()]
        out.append({"name": name, "layout": layout, "size": (w, h), "names": [_norm(n) for n in names]})
    return out


CATALOG = _parse()


COMBOS = [("banner", "(website|web site|landing page|homepage)", "Website Banner"),
          ("banner", "youtube", "YouTube Channel Banner"), ("cover", "facebook", "Facebook Cover Banner"),
          ("banner", "facebook", "Facebook Ads Banner"), ("banner", "linkedin", "LinkedIn Banner"),
          ("banner", "(email|newsletter)", "Email Marketing Banner"), ("banner", "(shop|store)", "E-commerce Store Banner"),
          ("(post|graphic)", "instagram", "Instagram Post"), ("(post|graphic)", "facebook", "Facebook Post"),
          ("story", "instagram", "Instagram Story"), ("story", "facebook", "Facebook Story"),
          ("cover", "tiktok", "TikTok Video Cover"), ("thumbnail", "youtube", "YouTube Thumbnail")]


def match(text):
    """'create a roll up banner for my coffee shop' -> the Roll-up Banner entry; None when no design type is named.
    The longest name found wins, so 'youtube thumbnail' beats 'thumbnail' and 'sale poster' beats 'poster'."""
    t = f" {_norm(text)} "
    t = re.sub(r"\b(\w{3,})s\b", r"\1", t)   # plurals: 'posters' -> 'poster'
    best, best_len = None, 0
    for entry in CATALOG:
        for n in entry["names"]:
            n2 = re.sub(r"\b(\w{3,})s\b", r"\1", n)
            if len(n2) > best_len and f" {n2} " in t:
                best, best_len = entry, len(n2)
    if best is None:   # "a banner for my website", "cover for my facebook page"
        for kind, place, name in COMBOS:
            if re.search(rf"\b{kind}\b", t) and re.search(rf"\b{place}\b", t):
                best = next(e for e in CATALOG if e["name"] == name)
                break
    if best is None and re.search(r"\bposter\b", t):   # any other poster
        best = next(e for e in CATALOG if e["name"] == "Promotional Poster")
    if best is None and re.search(r"\bbanner\b", t):
        best = next(e for e in CATALOG if e["name"] == "Sale Promotion Banner")
    return best


DESIGN_LAYOUTS = {"banner", "thumb", "square", "poster", "tall", "repeat"}


def for_photo(width, height):
    """No design type named ("redesign this"): keep the attached picture's shape."""
    r = width / max(height, 1)
    layout, size = (("banner", (1600, 900)) if r > 1.3 else ("square", (1080, 1080)) if r > 0.9
                    else ("poster", (1080, 1920)) if r < 0.65 else ("poster", (1080, 1350)))
    return {"name": "Design", "layout": layout, "size": size, "names": []}
