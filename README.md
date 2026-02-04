<div align="center">

# 📷 Fabula

A clean, lightweight, self-hosted photo gallery designed for tech-savvy photographers and photography enthusiasts, built with Flask.

![HTML5](https://img.shields.io/badge/html5-%23E34F26.svg?style=for-the-badge&logo=html5&logoColor=white) ![CSS3](https://img.shields.io/badge/css3-%231572B6.svg?style=for-the-badge&logo=css3&logoColor=white) ![JavaScript](https://img.shields.io/badge/javascript-%23323330.svg?style=for-the-badge&logo=javascript&logoColor=white) ![Flask](https://img.shields.io/badge/flask-%23000.svg?style=for-the-badge&logo=flask&logoColor=white)

</div>

<div align="center">
  <img src="/mockup.png?raw=true" alt="Mockup" width="700">
</div>

## Getting Started

### Installation

1. Clone the repo

```sh
 git clone https://github.com/S4kur4/fabula.git
```

2. Create username and password for managing photos

```sh
 /bin/bash account_init.sh
```
3. Modify `.env` to add your personal configuration

```
# (Optional) Google Analytics ID or Umami ID
GOOGLE_ANALYTICS_ID=
UMAMI_WEBSITE_ID=
```
```
# (Optional) Cloudflare Turnstile key to protect login form
TURNSTILE_SITE_KEY=
TURNSTILE_SECRET_KEY=
```
```
# Website title and your personal information
TITTLE='Vivian Kent Photography'

# About page - Main heading (can be different from title)
ABOUT_HEADING='Capturing the intersection of digital chaos and natural order.'

# About page - Introduction paragraphs (JSON array format)
ABOUT_ME='[
"Hello. I am Vivian Kent, a photographer living in Sydney, Australia.",
"I specialize in minimalist architectural photography and street portraits."
]'

# About page - Signature text (displayed at bottom of intro)
ABOUT_SIGNATURE='Vivian Kent'

# About page - Clients & Features (JSON array format)
ABOUT_CLIENTS='[
{"name": "Unsplash Editorial", "year": "2024"},
{"name": "Minimalissimo", "year": "2023"}
]'

# About page - Current Gear (JSON array format)
ABOUT_GEAR='[
{"category": "Main Body", "item": "Sony A7R V"},
{"category": "Daily Lens", "item": "35mm f/1.4 GM"}
]'

# About page - Contact information (JSON array format)
ABOUT_CONTACT='[
{"platform": "Twitter / X", "handle": "@vivian_photo"},
{"platform": "Instagram", "handle": "@vivian.raw"},
{"platform": "Email", "handle": "hello@viviankent.com"}
]'
```
```
# You can set the username and password directly here
# Note that the ADMIN_PASSWORD must be your password-hashed SHA256 value
ADMIN_USERNAME=admin
ADMIN_PASSWORD=
```
4.  Launch with `docker-compose`

```sh
docker-compose up -d
```

5. Use Nginx, Caddy and anyother popular web servers to point to `127.0.0.1:5001`

### Photo Management

Visit `/manage` to login and manage photos, and you can remove or bulk upload your photos.

## Support Me on Ko-fi

I create this project because I'm passionate about photography. If you'd like to support my work and help me dedicate more time to it, please consider supporting on Ko-fi. Thank you for your generosity!

<a href='https://ko-fi.com/E1E416MCAU' target='_blank'><img height='36' style='border:0px;height:36px;' src='https://storage.ko-fi.com/cdn/kofi6.png?v=6' border='0' alt='Buy Me a Coffee at ko-fi.com' /></a>
