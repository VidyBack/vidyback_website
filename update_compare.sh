#!/bin/bash

files=(
    "index.html"
    "about.html"
    "blog.html"
    "blog-post-1.html"
    "blog-post-2.html"
    "blog-post-3.html"
    "contact.html"
    "disclaimer.html"
    "faq.html"
    "features.html"
    "integrations.html"
    "platforms.html"
    "pricing.html"
    "privacypolicy.html"
    "shopify.html"
    "squarespace.html"
    "terms.html"
    "wix.html"
    "ecwid.html"
    "etsy.html"
    "jumpseller.html"
    "competitors.html"
    "minta-comparison.html"
    "outify-comparison.html"
)

for file in "${files[@]}"; do
    if [ -f "$file" ]; then
        sed -i '/<li><a href="competitors.html">vs Freelancers<\/a><\/li>/d' "$file"
        sed -i '/<li><a href="competitors.html">vs Agencies<\/a><\/li>/d' "$file"
        echo "Updated: $file"
    fi
done

echo "Done!"
