# Instagram Auto-Upload Setup Guide

## Prerequisites
1. Instagram **Business** or **Creator** account (API access required)
2. Facebook Page linked to Instagram account
3. Meta Developer account

## Step-by-Step Setup

### 1. Create Meta App
1. Go to https://developers.facebook.com/apps
2. Click "Create App" → "Business" type
3. Name: "YouTube Kids Automation"
4. Add "Instagram Graph API" product

### 2. Get Instagram Business Account ID
1. Graph API Explorer: https://developers.facebook.com/tools/explorer/
2. Select your app
3. Generate User Token with permissions:
   - `instagram_basic`
   - `instagram_content_publish`
   - `pages_read_engagement`
4. API call: `GET /me/accounts` (gets Facebook Pages)
5. Copy the Page ID
6. API call: `GET /{page-id}?fields=instagram_business_account`
7. Copy `instagram_business_account.id` → this is your `ig_user_id`

### 3. Generate Long-Lived Access Token
1. Short-lived tokens expire in 1 hour
2. Exchange for 60-day token: https://developers.facebook.com/docs/facebook-login/guides/access-tokens/get-long-lived
3. Save token → this is your `access_token`

### 4. Update config.yaml
```yaml
instagram:
  enabled: true
  ig_user_id: "17841400123456789"  # from step 2
  access_token: "EAABwzLixn..."     # from step 3
```

### 5. Test Upload
```bash
# Generate test video
python main.py --shorts --no-upload

# Then enable Instagram and run with upload
# Set instagram.enabled: true in config.yaml
python main.py --shorts
```

## Token Renewal (Every 60 Days)
Long-lived tokens expire after 60 days. Repeat step 3 every 2 months to renew.

## Safety Guidelines

### Safe Posting Frequency
- **Week 1-2**: 1 post/day (account warming)
- **Week 3+**: 2-3 posts/day max
- **Time gaps**: Minimum 30 minutes between posts
- **Current config**: 14 posts/week = 2/day (SAFE)

### Avoid Action Blocks
- Random jitter delays (5-30 min) prevent spam detection
- Don't post at exact same time daily
- Vary captions and hashtags slightly
- Monitor for "Action Blocked" warnings

### If Action Block Occurs
1. Stop all posting immediately
2. Wait 24-48 hours
3. Reduce posting frequency
4. Increase jitter delays

## Troubleshooting
- **Error 190**: Token expired → renew token (step 3)
- **Error 36000**: Video >3 minutes (reels limit)
- **Error 100**: Invalid `ig_user_id`
- **Action block**: Posting too fast → increase jitter, reduce frequency
