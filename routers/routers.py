import os
import csv
from io import StringIO
import traceback
import time
from datetime import datetime, timezone, timedelta
import requests
import pymysql
from sqlalchemy.orm import Session
from dotenv import load_dotenv, set_key
from fastapi import APIRouter,HTTPException, status, Depends
from fastapi.responses import JSONResponse, StreamingResponse
from database.models import SocialMedia
from utilities.access_token import refresh_access_token, is_access_token_expired, generate_new_long_lived_token
from database.database import get_db

router = APIRouter()

load_dotenv()

DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME")
DB_HOST = os.getenv("DB_HOST")
BASE_URL = os.getenv("BASE_URL")
ZING_ACCESS_TOKEN = os.getenv("ZING_ACCESS_TOKEN")
ZING_INSTAGRAM_ACCOUNT_ID = os.getenv("ZING_INSTAGRAM_ACCOUNT_ID")
APP_ID = os.getenv("META_APP_ID")
APP_SECRET = os.getenv("META_APP_SECRET")
LONG_LIVED_TOKEN = os.getenv("LONG_LIVED_TOKEN")

@router.get("/fetch_insights_zing")
def fetch_insights_zing(db: Session = Depends(get_db)):
    """
    Fetch a summarized version of Instagram insights, showing only important metrics.
    Automatically refreshes access token if needed.
    """
    try:
        global ZING_ACCESS_TOKEN
        # Refresh the short-lived token
        if is_access_token_expired(ZING_ACCESS_TOKEN):
            try:
                refreshed_token = refresh_access_token(APP_ID, APP_SECRET, LONG_LIVED_TOKEN)
                # Update the .env file and reload the environment
                set_key('.env', 'ZING_ACCESS_TOKEN', refreshed_token)
                load_dotenv()  # Reload the updated .env file
                ZING_ACCESS_TOKEN = os.getenv("ZING_ACCESS_TOKEN")  # Get updated token
            except Exception as e:
                try:
                    new_long_lived_token = generate_new_long_lived_token()
                    set_key('.env', 'LONG_LIVED_TOKEN', new_long_lived_token)
                    load_dotenv()  # Reload the updated .env file
                    # Now use the new long-lived token to generate a new short-lived (ZING) access token
                    # Here we assume that generate_zing_access_token uses long-lived token to create the short-lived one
                    new_zing_access_token = refresh_access_token(APP_ID,APP_SECRET,new_long_lived_token)
                    set_key('.env', 'ZING_ACCESS_TOKEN', new_zing_access_token)
                    load_dotenv()  # Reload the updated .env file
                    ZING_ACCESS_TOKEN = os.getenv("ZING_ACCESS_TOKEN")
                except Exception as gen_error:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"Failed to generate new long-lived token: {str(gen_error)}"
                    )
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to refresh access token: {str(e)}"
                )

        # Fetch Instagram account details
        account_url = f"{BASE_URL}{ZING_INSTAGRAM_ACCOUNT_ID}?fields=id,username,followers_count&access_token={ZING_ACCESS_TOKEN}"
        account_response = requests.get(account_url)

        if account_response.status_code != 200:
            raise HTTPException(
                status_code=account_response.status_code,
                detail=f"Failed to fetch account details: {account_response.text}"
            )
        account_data = account_response.json()

        # Fetch insights
        insights_url = f"{BASE_URL}{ZING_INSTAGRAM_ACCOUNT_ID}/insights?metric=impressions,reach,accounts_engaged,website_clicks&period=day&metric_type=total_value&access_token={ZING_ACCESS_TOKEN}"
        insights_response = requests.get(insights_url)

        if insights_response.status_code != 200:
            raise HTTPException(
                status_code=insights_response.status_code,
                detail=f"Failed to fetch insights: {insights_response.text}"
            )
        insights_data = insights_response.json()

        # Extract insights
        impressions, reach, accounts_engaged, website_clicks = None, None, None, None

        for item in insights_data.get("data", []):
            if item.get("name") == "impressions" and "total_value" in item:
                impressions = item["total_value"].get("value")
            if item.get("name") == "reach" and "total_value" in item:
                reach = item["total_value"].get("value")
            if item.get("name") == "accounts_engaged" and "total_value" in item:
                accounts_engaged = item["total_value"].get("value")
            if item.get("name") == "website_clicks" and "total_value" in item:
                website_clicks = item["total_value"].get("value")

        # Combine results
        result = {
            "username": account_data.get("username"),
            "followers_count": account_data.get("followers_count"),
            "impressions": impressions,
            "reach": reach,
            "accounts_engaged": accounts_engaged,
            "website_clicks" : website_clicks
        }
        # Retrieve the last inserted record
        last_record = db.query(SocialMedia).order_by(SocialMedia.created_ts.desc()).first()
        # Compute new values
        if last_record:
            new_followers = result["followers_count"] - (last_record.followers or 0)
            new_impressions = result["impressions"] - (last_record.impressions or 0)
            new_reach = result["reach"] - (last_record.reach or 0)
            new_accounts_engaged = result["accounts_engaged"] - (last_record.accounts_engaged or 0)
            new_website_clicks = result["website_clicks"] - (last_record.website_clicks or 0)
        else:
            new_followers = result["followers_count"]
            new_impressions = result["impressions"]
            new_reach = result["reach"]
            new_accounts_engaged = result["accounts_engaged"]
            new_website_clicks = result["website_clicks"]
       # Store data in the database using SQLAlchemy
        # Insert new record
        try:
            socialmedia_analytics = SocialMedia(
                username=result["username"],
                followers=new_followers,
                impressions=new_impressions,
                reach=new_reach,
                accounts_engaged=new_accounts_engaged,
                website_clicks=new_website_clicks,
                created_ts=datetime.now(timezone.utc)
            )
            db.add(socialmedia_analytics)
            db.commit()
            db.refresh(socialmedia_analytics)
        except Exception as e:
            db.rollback()
            traceback.print_exc()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to insert data into database"
            )
        
         # Write the result to a CSV file
        try:
            with open('instagram_insights.csv', mode='a', newline='') as file:
                writer = csv.DictWriter(file, fieldnames=result.keys())
                if file.tell() == 0:
                    writer.writeheader()  # Write header only if file is empty
                writer.writerow(result)
        except Exception as e:
            traceback.print_exc()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to write to CSV: {str(e)}"
            )
        return JSONResponse(content=result)

    except HTTPException as e:
        traceback.print_exc()
        return JSONResponse(status_code=e.status_code, content={"error": e.detail})
    except Exception:
        traceback.print_exc()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"error": "Something went wrong."})

@router.get("/engaged_audience_demographics")
def engaged_audience_demographics():
    try:
        global ZING_ACCESS_TOKEN
        # Refresh the short-lived token
        if is_access_token_expired(ZING_ACCESS_TOKEN):
            try:
                refreshed_token = refresh_access_token(APP_ID, APP_SECRET, LONG_LIVED_TOKEN)
                # Update the .env file and reload the environment
                set_key('.env', 'ZING_ACCESS_TOKEN', refreshed_token)
                load_dotenv()  # Reload the updated .env file
                ZING_ACCESS_TOKEN = os.getenv("ZING_ACCESS_TOKEN")  # Get updated token
            except Exception as e:
                try:
                    new_long_lived_token = generate_new_long_lived_token()
                    set_key('.env', 'LONG_LIVED_TOKEN', new_long_lived_token)
                    load_dotenv()  # Reload the updated .env file
                    # Now use the new long-lived token to generate a new short-lived (ZING) access token
                    # Here we assume that generate_zing_access_token uses long-lived token to create the short-lived one
                    new_zing_access_token = refresh_access_token(APP_ID,APP_SECRET,new_long_lived_token)
                    set_key('.env', 'ZING_ACCESS_TOKEN', new_zing_access_token)
                    load_dotenv()  # Reload the updated .env file
                    ZING_ACCESS_TOKEN = os.getenv("ZING_ACCESS_TOKEN")
                except Exception as gen_error:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"Failed to generate new long-lived token: {str(gen_error)}"
                    )
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to refresh access token: {str(e)}"
                )
        # Get timestamps for the last 24 hours
        until_timestamp = int(datetime.now(timezone.utc).timestamp())
        since_timestamp = until_timestamp - 86400  # 24 hours ago
            # Fetch engaged audience demographics
        engaged_audience_age_url = f"{BASE_URL}{ZING_INSTAGRAM_ACCOUNT_ID}/insights?metric=engaged_audience_demographics&period=lifetime&timeframe=this_week&since={since_timestamp}&until={until_timestamp}&metric_type=total_value&breakdown=age&access_token={ZING_ACCESS_TOKEN}"
        engaged_audience_age_response = requests.get(engaged_audience_age_url)
        engaged_audience_gender_url = f"{BASE_URL}{ZING_INSTAGRAM_ACCOUNT_ID}/insights?metric=engaged_audience_demographics&period=lifetime&timeframe=this_week&since={since_timestamp}&until={until_timestamp}&metric_type=total_value&breakdown=gender&access_token={ZING_ACCESS_TOKEN}"
        engaged_audience_gender_response = requests.get(engaged_audience_gender_url)
        engaged_audience_city_url = f"{BASE_URL}{ZING_INSTAGRAM_ACCOUNT_ID}/insights?metric=engaged_audience_demographics&period=lifetime&timeframe=this_week&since={since_timestamp}&until={until_timestamp}&metric_type=total_value&breakdown=city&access_token={ZING_ACCESS_TOKEN}"
        engaged_audience_city_response = requests.get(engaged_audience_city_url)

        if engaged_audience_age_response.status_code != 200:
            raise HTTPException(
                status_code=engaged_audience_age_response.status_code,
                detail=f"Failed to fetch engaged audience age group: {engaged_audience_age_response.text}"
            )
        
        if engaged_audience_gender_response.status_code != 200:
            raise HTTPException(
                status_code=engaged_audience_gender_response.status_code,
                detail = f"Failed to fetch engaged audience gender distribution: {engaged_audience_gender_response.text}"
            )
        
        if engaged_audience_city_response.status_code != 200:
            raise HTTPException(
                status_code=engaged_audience_city_response.status_code,
                detail = f"Failed to fetch engaged audience city distribution: {engaged_audience_city_response.text}"
            )

        engaged_audience_age_data = engaged_audience_age_response.json()
        engaged_audience_gender_data = engaged_audience_gender_response.json()
        engaged_audience_city_data = engaged_audience_city_response.json()

         # Initialize age_group to hold the processed values
        age_group = []
        # Loop through the demographics data to get the age breakdown
        for item in engaged_audience_age_data.get("data", []):
            if item.get("name") == "engaged_audience_demographics" and "total_value" in item:
                breakdowns = item["total_value"].get("breakdowns", [])
                
                for breakdown in breakdowns:
                    if "results" in breakdown:
                        for result in breakdown["results"]:
                            age_range = result.get("dimension_values", [])
                            count = result.get("value")
                            if age_range:
                                # Append a dictionary with age range and count
                                age_group.append({
                                    "age_range": age_range[0],
                                    "count": count
                                })
        gender_distribution = []
        for item in engaged_audience_gender_data.get("data", []):
            if item.get("name") == "engaged_audience_demographics" and "total_value" in item:
                breakdowns = item["total_value"].get("breakdowns", [])

                for breakdown in breakdowns:
                    if "results" in breakdown:
                        for result in breakdown["results"]:
                            gender_dist = result.get("dimension_values", [])
                            count_gd = result.get("value")
                            if gender_dist:
                                gender_distribution.append({
                                    "gender": gender_dist[0],
                                    "count": count_gd
                                })
        city_distribution = []
        for item in engaged_audience_city_data.get("data", []):
            if item.get("name") == "engaged_audience_demographics" and "total_value" in item:
                breakdowns = item["total_value"].get("breakdowns", [])

                for breakdown in breakdowns:
                    if "results" in breakdown:
                        for result in breakdown["results"]:
                            city_dist = result.get("dimension_values", [])
                            count_cd = result.get("value")
                            if city_dist:
                                city_distribution.append(
                                    {
                                        "city": city_dist[0],
                                        "count": count_cd
                                    }
                                )
        result = {
            "age_group": age_group,
            "gender_distribution": gender_distribution,
            "city_distribution": city_distribution
        }

        # Prepare data for CSV
        output = StringIO()
        csv_writer = csv.DictWriter(output, fieldnames=["age_range", "count", "gender", "gender_count", "city", "city_count"])
        csv_writer.writeheader()

        # Combine all three groups into one list to write to CSV
        max_length = max(len(age_group), len(gender_distribution), len(city_distribution))
        for i in range(max_length):
            row = {
                "age_range": age_group[i]["age_range"] if i < len(age_group) else "",
                "count": age_group[i]["count"] if i < len(age_group) else "",
                "gender": gender_distribution[i]["gender"] if i < len(gender_distribution) else "",
                "gender_count": gender_distribution[i]["count"] if i < len(gender_distribution) else "",
                "city": city_distribution[i]["city"] if i < len(city_distribution) else "",
                "city_count": city_distribution[i]["count"] if i < len(city_distribution) else ""
            }
            csv_writer.writerow(row)

        output.seek(0)
        return StreamingResponse(output, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=engaged_audience_demographics.csv"})

    except HTTPException as e:
        traceback.print_exc()
        return JSONResponse(status_code=e.status_code, content={"error": e.detail})
    except Exception:
        traceback.print_exc()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"error": "Something went wrong."})


@router.get("/fetch_top_posts")
def fetch_top_posts():
    try:
        global ZING_ACCESS_TOKEN
        # Refresh the short-lived token
        if is_access_token_expired(ZING_ACCESS_TOKEN):
            try:
                refreshed_token = refresh_access_token(APP_ID, APP_SECRET, LONG_LIVED_TOKEN)
                set_key('.env', 'ZING_ACCESS_TOKEN', refreshed_token)
                load_dotenv()  # Reload the updated .env file
                ZING_ACCESS_TOKEN = os.getenv("ZING_ACCESS_TOKEN")  # Get updated token
            except Exception as e:
                try:
                    new_long_lived_token = generate_new_long_lived_token()
                    set_key('.env', 'LONG_LIVED_TOKEN', new_long_lived_token)
                    load_dotenv()  # Reload the updated .env file
                    new_zing_access_token = refresh_access_token(APP_ID, APP_SECRET, new_long_lived_token)
                    set_key('.env', 'ZING_ACCESS_TOKEN', new_zing_access_token)
                    load_dotenv()  # Reload the updated .env file
                    ZING_ACCESS_TOKEN = os.getenv("ZING_ACCESS_TOKEN")
                except Exception as gen_error:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"Failed to generate new long-lived token: {str(gen_error)}"
                    )
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to refresh access token: {str(e)}"
                )

        # Calculate the date one month ago
        one_month_ago = datetime.now(timezone.utc) - timedelta(days=30)

        # Fetch top-performing posts and reels
        posts_url = f"{BASE_URL}{ZING_INSTAGRAM_ACCOUNT_ID}/media?fields=id,media_type,media_url,timestamp&access_token={ZING_ACCESS_TOKEN}"
        posts_response = requests.get(posts_url)

        if posts_response.status_code != 200:
            raise HTTPException(
                status_code=posts_response.status_code,
                detail=f"Failed to fetch posts: {posts_response.text}"
            )
        posts_data = posts_response.json()

        # Filter posts from the last month
        recent_posts = []
        for post in posts_data.get("data", []):
            # Convert timestamp to proper UTC format
            raw_timestamp = post.get("timestamp")
            if raw_timestamp:
                utc_time = datetime.strptime(raw_timestamp, "%Y-%m-%dT%H:%M:%S%z")
                formatted_utc_time = utc_time.strftime("%Y-%m-%d %H:%M:%S")
                
                # Add to recent posts if within the last month
                if utc_time >= one_month_ago:
                    recent_posts.append({
                        "post_id": post.get("id"),
                        "media_type": post.get("media_type"),
                        "media_url": post.get("media_url"),
                        "timestamp": formatted_utc_time  # Store formatted timestamp
                    })

        # Count the number of recent posts
        total_recent_posts = len(recent_posts)

        # Extract top-performing posts and reels
        top_posts = []
        for post in recent_posts:
            post_id = post.get("post_id")
            media_type = post.get("media_type")
            media_url = post.get("media_url")
            post_created = post.get("timestamp")

            if not media_url:
                continue

            # Fetch likes
            likes_url = f"{BASE_URL}{post_id}?fields=like_count&access_token={ZING_ACCESS_TOKEN}"
            likes_response = requests.get(likes_url)

            if likes_response.status_code != 200:
                raise HTTPException(
                    status_code=likes_response.status_code,
                    detail=f"Failed to fetch likes: {likes_response.text}"
                )
            like_metrics = likes_response.json()
            like_count = like_metrics.get("like_count", 0)

            # Fetch insights for posts and reels
            insights_url = f"{BASE_URL}{post_id}/insights?metric=reach&access_token={ZING_ACCESS_TOKEN}"
            insights_response = requests.get(insights_url)

            if insights_response.status_code != 200:
                raise HTTPException(
                    status_code=insights_response.status_code,
                    detail=f"Failed to fetch insights: {insights_response.text}"
                )
            post_insights = insights_response.json()

            saves_url = f"{BASE_URL}{post_id}/insights?metric=saved&access_token={ZING_ACCESS_TOKEN}"
            saves_response = requests.get(saves_url)

            if saves_response.status_code != 200:
                raise HTTPException(
                    status_code=saves_response.status_code,
                    detail=f"Failed to fetch saves: {saves_response.text}"
                )
            save_insights = saves_response.json()

            reach = None
            for insight in post_insights.get("data", []):
                if insight.get("name") == "reach":
                    reach = insight.get("values", [{}])[0].get("value")
                    break
            
            saves = None
            for insight in save_insights.get("data", []):
                if insight.get("name") == "saved":
                    saves = insight.get("values", [{}])[0].get("value")
            if reach or like_count or saves:
                top_posts.append({
                    "post_id": post_id,
                    "media_type": media_type,
                    "media_url": media_url,
                    "post_created": post_created,  # Already formatted
                    "reach": reach,
                    "likes":like_count,
                    "saves": saves
                })

        # Sort posts by reach in descending order and take the top 5
        top_posts = sorted(top_posts, key=lambda x: x["reach"], reverse=True)[:5]
        result = {
            "total_recent_posts": total_recent_posts,
            "top_posts": top_posts
        }
        return JSONResponse(content=result)

    except HTTPException as e:
        traceback.print_exc()
        return JSONResponse(status_code=e.status_code, content={"error": e.detail})
    except Exception:
        traceback.print_exc()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"error": "Something went wrong."})
    
@router.get("/fetch_today_posts")
def fetch_today_posts():
    try:
        global ZING_ACCESS_TOKEN
        # Refresh the short-lived token
        if is_access_token_expired(ZING_ACCESS_TOKEN):
            try:
                refreshed_token = refresh_access_token(APP_ID, APP_SECRET, LONG_LIVED_TOKEN)
                set_key('.env', 'ZING_ACCESS_TOKEN', refreshed_token)
                load_dotenv()  # Reload the updated .env file
                ZING_ACCESS_TOKEN = os.getenv("ZING_ACCESS_TOKEN")  # Get updated token
            except Exception as e:
                try:
                    new_long_lived_token = generate_new_long_lived_token()
                    set_key('.env', 'LONG_LIVED_TOKEN', new_long_lived_token)
                    load_dotenv()  # Reload the updated .env file
                    new_zing_access_token = refresh_access_token(APP_ID, APP_SECRET, new_long_lived_token)
                    set_key('.env', 'ZING_ACCESS_TOKEN', new_zing_access_token)
                    load_dotenv()  # Reload the updated .env file
                    ZING_ACCESS_TOKEN = os.getenv("ZING_ACCESS_TOKEN")
                except Exception as gen_error:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"Failed to generate new long-lived token: {str(gen_error)}"
                    )
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to refresh access token: {str(e)}"
                )

        # Get the current date to filter posts (today's date)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Fetch all posts for today
        posts_url = f"{BASE_URL}{ZING_INSTAGRAM_ACCOUNT_ID}/media?fields=id,media_type,media_url,timestamp&access_token={ZING_ACCESS_TOKEN}"
        posts_response = requests.get(posts_url)

        if posts_response.status_code != 200:
            raise HTTPException(
                status_code=posts_response.status_code,
                detail=f"Failed to fetch posts: {posts_response.text}"
            )
        posts_data = posts_response.json()

        # Filter posts from today based on the timestamp
        todays_posts = []
        for post in posts_data.get("data", []):
            raw_timestamp = post.get("timestamp")
            if raw_timestamp:
                utc_time = datetime.strptime(raw_timestamp, "%Y-%m-%dT%H:%M:%S%z")
                formatted_utc_time = utc_time.strftime("%Y-%m-%d")
                
                # Include post if it matches today's date
                if formatted_utc_time == today:
                    todays_posts.append({
                        "post_id": post.get("id"),
                        "media_type": post.get("media_type"),
                        "media_url": post.get("media_url"),
                        "timestamp": formatted_utc_time  # Store formatted timestamp
                    })

        if not todays_posts:
            return JSONResponse(content={"message": "No posts found for today."})

        # Fetch metrics for each post (reach, likes, saves)
        post_metrics = []
        for post in todays_posts:
            post_id = post.get("post_id")
            media_type = post.get("media_type")
            media_url = post.get("media_url")
            post_created = post.get("timestamp")

            # Fetch likes
            likes_url = f"{BASE_URL}{post_id}?fields=like_count&access_token={ZING_ACCESS_TOKEN}"
            likes_response = requests.get(likes_url)

            if likes_response.status_code != 200:
                raise HTTPException(
                    status_code=likes_response.status_code,
                    detail=f"Failed to fetch likes: {likes_response.text}"
                )
            like_metrics = likes_response.json()
            like_count = like_metrics.get("like_count", 0)

            # Fetch insights for reach
            insights_url = f"{BASE_URL}{post_id}/insights?metric=reach&access_token={ZING_ACCESS_TOKEN}"
            insights_response = requests.get(insights_url)

            if insights_response.status_code != 200:
                raise HTTPException(
                    status_code=insights_response.status_code,
                    detail=f"Failed to fetch insights: {insights_response.text}"
                )
            post_insights = insights_response.json()

            # Fetch saves
            saves_url = f"{BASE_URL}{post_id}/insights?metric=saved&access_token={ZING_ACCESS_TOKEN}"
            saves_response = requests.get(saves_url)

            if saves_response.status_code != 200:
                raise HTTPException(
                    status_code=saves_response.status_code,
                    detail=f"Failed to fetch saves: {saves_response.text}"
                )
            save_insights = saves_response.json()

            reach = None
            for insight in post_insights.get("data", []):
                if insight.get("name") == "reach":
                    reach = insight.get("values", [{}])[0].get("value")
                    break

            saves = None
            for insight in save_insights.get("data", []):
                if insight.get("name") == "saved":
                    saves = insight.get("values", [{}])[0].get("value")

            post_metrics.append({
                "post_id": post_id,
                "media_type": media_type,
                "media_url": media_url,
                "post_created": post_created,  # Already formatted
                "reach": reach,
                "likes": like_count,
                "saves": saves
            })

        result = {
            "total_posts_today": len(todays_posts),
            "posts": post_metrics
        }

        return JSONResponse(content=result)

    except HTTPException as e:
        traceback.print_exc()
        return JSONResponse(status_code=e.status_code, content={"error": e.detail})
    except Exception:
        traceback.print_exc()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"error": "Something went wrong."})

# @router.get("/fetch_all_posts")
# def fetch_all_posts(db: Session = Depends(get_db)):
#     try:
#         # Initialize variables to store all posts
#         all_posts = []
        
#         # Paginate through all posts from the Instagram API
#         posts_url = f"{BASE_URL}{ZING_INSTAGRAM_ACCOUNT_ID}/media?fields=id,media_type,media_url,timestamp&access_token={ZING_ACCESS_TOKEN}"
#         while posts_url:
#             posts_response = requests.get(posts_url)

#             if posts_response.status_code != 200:
#                 raise HTTPException(
#                     status_code=posts_response.status_code,
#                     detail=f"Failed to fetch posts: {posts_response.text}"
#                 )

#             posts_data = posts_response.json()
#             all_posts.extend(posts_data.get("data", []))
#             # Check if there's a next page
#             posts_url = posts_data.get("paging", {}).get("next")

#         # If no posts found, return a message
#         if not all_posts:
#             return JSONResponse(content={"message": "No posts found."})

#         # Prepare the response by fetching metrics for each post
#         post_metrics = []
#         for post in all_posts:
#             post_id = post.get("id")
#             media_type = post.get("media_type")
#             media_url = post.get("media_url")
#             raw_timestamp = post.get("timestamp")

#             # Format timestamp
#             post_created = None
#             if raw_timestamp:
#                 utc_time = datetime.strptime(raw_timestamp, "%Y-%m-%dT%H:%M:%S%z")
#                 post_created = utc_time.strftime("%Y-%m-%d")

#             # Insert post details into `Posts` table
#             db_post = Posts(post_id=post_id, media_type=media_type, media_url=media_url, post_created=post_created)
#             db.add(db_post)
#             db.commit()

#             # Fetch likes
#             likes_url = f"{BASE_URL}{post_id}?fields=like_count&access_token={ZING_ACCESS_TOKEN}"
#             likes_response = requests.get(likes_url)

#             if likes_response.status_code != 200:
#                 raise HTTPException(
#                     status_code=likes_response.status_code,
#                     detail=f"Failed to fetch likes: {likes_response.text}"
#                 )
#             like_metrics = likes_response.json()
#             like_count = like_metrics.get("like_count", 0)

#             # Fetch insights for reach
#             insights_url = f"{BASE_URL}{post_id}/insights?metric=reach&access_token={ZING_ACCESS_TOKEN}"
#             insights_response = requests.get(insights_url)

#             if insights_response.status_code != 200:
#                 raise HTTPException(
#                     status_code=insights_response.status_code,
#                     detail=f"Failed to fetch insights: {insights_response.text}"
#                 )
#             post_insights = insights_response.json()

#             # Fetch saves
#             saves_url = f"{BASE_URL}{post_id}/insights?metric=saved&access_token={ZING_ACCESS_TOKEN}"
#             saves_response = requests.get(saves_url)

#             if saves_response.status_code != 200:
#                 raise HTTPException(
#                     status_code=saves_response.status_code,
#                     detail=f"Failed to fetch saves: {saves_response.text}"
#                 )
#             save_insights = saves_response.json()

#             # Extract reach and saves values
#             reach = None
#             for insight in post_insights.get("data", []):
#                 if insight.get("name") == "reach":
#                     reach = insight.get("values", [{}])[0].get("value")
#                     break

#             saves = None
#             for insight in save_insights.get("data", []):
#                 if insight.get("name") == "saved":
#                     saves = insight.get("values", [{}])[0].get("value")

#             # Insert insights into `PostInsights` table
#             db_insight = PostInsights(
#                 posts_id=db_post.id, reach=reach, likes=like_count, saves=saves
#             )
#             db.add(db_insight)
#             db.commit()
#             # Add the post details to the metrics list
#             post_metrics.append({
#                 "post_id": post_id,
#                 "media_type": media_type,
#                 "media_url": media_url,
#                 "post_created": post_created,
#                 "reach": reach,
#                 "likes": like_count,
#                 "saves": saves
#             })

#         # Prepare the final response
#         result = {
#             "total_posts": len(post_metrics),
#             "posts": post_metrics
#         }

#         return JSONResponse(content=f"Successfully Retrieved and Added the Data Into Database {result}")

#     except HTTPException as e:
#         traceback.print_exc()
#         return JSONResponse(status_code=e.status_code, content={"error": e.detail})
#     except Exception:
#         traceback.print_exc()
#         return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"error": "Something went wrong."})