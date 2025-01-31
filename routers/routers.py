import os
import csv
from io import StringIO
import traceback
import time
from datetime import datetime, timezone, timedelta
import requests
import pymysql
from sqlalchemy import func
from sqlalchemy.orm import Session
from dotenv import load_dotenv, set_key
from fastapi import APIRouter,HTTPException, status, Depends
from fastapi.responses import JSONResponse, StreamingResponse
from database.models import SocialMedia, EngagedAudienceAge, EngagedAudienceGender, EngagedAudienceLocation, PostInsights,Posts
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

        # Get today's date (without time) in UTC
        today_date = datetime.now(timezone.utc).date()

        # Check if a record for today already exists
        existing_record = db.query(SocialMedia).filter(func.date(SocialMedia.created_ts) == today_date).first()

        if existing_record:
            # If a record exists, update the counts based on the new fetched data
            existing_record.followers = result["followers_count"] - db.query(func.sum(SocialMedia.followers)).scalar() or 0
            existing_record.impressions = result["impressions"] - db.query(func.sum(SocialMedia.impressions)).scalar() or 0
            existing_record.reach = result["reach"] - db.query(func.sum(SocialMedia.reach)).scalar() or 0
            existing_record.accounts_engaged = result["accounts_engaged"] - db.query(func.sum(SocialMedia.accounts_engaged)).scalar() or 0
            existing_record.website_clicks = result["website_clicks"] - db.query(func.sum(SocialMedia.website_clicks)).scalar() or 0

            db.commit()  # Commit the changes to the database
            db.refresh(existing_record)  # Refresh the record to get the updated data
        else:
            # If no record exists for today, insert a new one
            try:
                socialmedia_analytics = SocialMedia(
                    username=result["username"],
                    followers=result["followers_count"],
                    impressions=result["impressions"],
                    reach=result["reach"],
                    accounts_engaged=result["accounts_engaged"],
                    website_clicks=result["website_clicks"],
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

        return JSONResponse(content=result)

    except HTTPException as e:
        db.rollback()
        traceback.print_exc()
        return JSONResponse(status_code=e.status_code, content={"error": e.detail})
    except Exception:
        db.rollback()
        traceback.print_exc()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"error": "Something went wrong."})

@router.get("/engaged_audience_demographics")
def engaged_audience_demographics(db: Session = Depends(get_db)):
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
        today_date = datetime.now(timezone.utc).date()
            # Fetch engaged audience demographics
        engaged_audience_age_url = f"{BASE_URL}{ZING_INSTAGRAM_ACCOUNT_ID}/insights?metric=engaged_audience_demographics&period=lifetime&timeframe=this_week&metric_type=total_value&breakdown=age&access_token={ZING_ACCESS_TOKEN}"
        engaged_audience_age_response = requests.get(engaged_audience_age_url)
        engaged_audience_gender_url = f"{BASE_URL}{ZING_INSTAGRAM_ACCOUNT_ID}/insights?metric=engaged_audience_demographics&period=lifetime&timeframe=this_week&metric_type=total_value&breakdown=gender&access_token={ZING_ACCESS_TOKEN}"
        engaged_audience_gender_response = requests.get(engaged_audience_gender_url)
        engaged_audience_city_url = f"{BASE_URL}{ZING_INSTAGRAM_ACCOUNT_ID}/insights?metric=engaged_audience_demographics&period=lifetime&timeframe=this_week&metric_type=total_value&breakdown=city&access_token={ZING_ACCESS_TOKEN}"
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

        # Retrieve the latest socialmedia record for today's date
        socialmedia_entry = (
            db.query(SocialMedia)
            .filter(func.date(SocialMedia.created_ts) == today_date)
            .order_by(SocialMedia.created_ts.desc())  # Get the latest entry
            .first()
        )
        if not socialmedia_entry:
            raise HTTPException(status_code=404, detail="Social media record not found.")
        
        socialmedia_id = socialmedia_entry.id

        # Initialize age_group, gender_distribution, and city_distribution to hold the processed values
        age_group = []
        gender_distribution = []
        city_distribution = []

        # Loop through the demographics data to get the age breakdown
        for item in engaged_audience_age_data.get("data", []):
            if item.get("name") == "engaged_audience_demographics" and "total_value" in item:
                breakdowns = item["total_value"].get("breakdowns", [])
                for breakdown in breakdowns:
                    if "results" in breakdown:
                        for result in breakdown["results"]:
                            age_range = result.get("dimension_values", [])
                            new_count = result.get("value")
                            if age_range:
                                # Fetch the sum of all existing counts for this age_group
                                existing_total = db.query(func.sum(EngagedAudienceAge.count)).filter(
                                    EngagedAudienceAge.socialmedia_id == socialmedia_id,
                                    EngagedAudienceAge.age_group == age_range[0],
                                    func.date(EngagedAudienceAge.created_ts) == today_date
                                ).scalar() or 0  # Default to 0 if no records exist

                                # Calculate the difference: new_count - existing_total
                                count_difference = new_count - existing_total

                                # Fetch the existing entry for the current day
                                existing_entry = db.query(EngagedAudienceAge).filter(
                                    EngagedAudienceAge.socialmedia_id == socialmedia_id,
                                    EngagedAudienceAge.age_group == age_range[0],
                                    func.date(EngagedAudienceAge.created_ts) == today_date
                                ).first()

                                if existing_entry:
                                    # Update the existing record by adding the difference
                                    existing_entry.count += count_difference
                                    db.flush()
                                    db.refresh(existing_entry)
                                else:
                                    # If no existing entry for today, create a new one with the new count
                                    age_instance = EngagedAudienceAge(
                                        socialmedia_id=socialmedia_id,
                                        age_group=age_range[0],
                                        count=new_count,
                                        created_ts=datetime.now(timezone.utc)
                                    )
                                    db.add(age_instance)

                                # Append the processed data to the age_group list
                                age_group.append({
                                    "age_range": age_range[0],
                                    "count": new_count
                                })

        # Process gender distribution
        for item in engaged_audience_gender_data.get("data", []):
            if item.get("name") == "engaged_audience_demographics" and "total_value" in item:
                breakdowns = item["total_value"].get("breakdowns", [])
                for breakdown in breakdowns:
                    if "results" in breakdown:
                        for result in breakdown["results"]:
                            gender_dist = result.get("dimension_values", [])
                            new_count = result.get("value")
                            if gender_dist:
                                # Fetch the sum of all existing counts for this gender
                                existing_total = db.query(func.sum(EngagedAudienceGender.count)).filter(
                                    EngagedAudienceGender.socialmedia_id == socialmedia_id,
                                    EngagedAudienceGender.gender == gender_dist[0],
                                    func.date(EngagedAudienceGender.created_ts) == today_date
                                ).scalar() or 0  # Default to 0 if no records exist

                                # Calculate the difference: new_count - existing_total
                                count_difference = new_count - existing_total

                                # Fetch the existing entry for the current day
                                existing_entry = db.query(EngagedAudienceGender).filter(
                                    EngagedAudienceGender.socialmedia_id == socialmedia_id,
                                    EngagedAudienceGender.gender == gender_dist[0],
                                    func.date(EngagedAudienceGender.created_ts) == today_date
                                ).first()

                                if existing_entry:
                                    # Update the existing record by adding the difference
                                    existing_entry.count += count_difference
                                    db.flush()
                                    db.refresh(existing_entry)
                                else:
                                    # If no existing entry for today, create a new one with the new count
                                    gender_instance = EngagedAudienceGender(
                                        socialmedia_id=socialmedia_id,
                                        gender=gender_dist[0],
                                        count=new_count,
                                        created_ts=datetime.now(timezone.utc)
                                    )
                                    db.add(gender_instance)

                                # Append the processed data to the gender_distribution list
                                gender_distribution.append({
                                    "gender": gender_dist[0],
                                    "count": new_count
                                })

        # Process city distribution
        for item in engaged_audience_city_data.get("data", []):
            if item.get("name") == "engaged_audience_demographics" and "total_value" in item:
                breakdowns = item["total_value"].get("breakdowns", [])
                for breakdown in breakdowns:
                    if "results" in breakdown:
                        for result in breakdown["results"]:
                            city_dist = result.get("dimension_values", [])
                            new_count = result.get("value")
                            if city_dist:
                                # Fetch the sum of all existing counts for this city
                                existing_total = db.query(func.sum(EngagedAudienceLocation.count)).filter(
                                    EngagedAudienceLocation.socialmedia_id == socialmedia_id,
                                    EngagedAudienceLocation.city == city_dist[0],
                                    func.date(EngagedAudienceLocation.created_ts) == today_date
                                ).scalar() or 0  # Default to 0 if no records exist

                                # Calculate the difference: new_count - existing_total
                                count_difference = new_count - existing_total

                                # Fetch the existing entry for the current day
                                existing_entry = db.query(EngagedAudienceLocation).filter(
                                    EngagedAudienceLocation.socialmedia_id == socialmedia_id,
                                    EngagedAudienceLocation.city == city_dist[0],
                                    func.date(EngagedAudienceLocation.created_ts) == today_date
                                ).first()

                                if existing_entry:
                                    # Update the existing record by adding the difference
                                    existing_entry.count += count_difference
                                    db.flush()
                                    db.refresh(existing_entry)
                                else:
                                    # If no existing entry for today, create a new one with the new count
                                    city_instance = EngagedAudienceLocation(
                                        socialmedia_id=socialmedia_id,
                                        city=city_dist[0],
                                        count=new_count,
                                        created_ts=datetime.now(timezone.utc)
                                    )
                                    db.add(city_instance)

                                # Append the processed data to the city_distribution list
                                city_distribution.append({
                                    "city": city_dist[0],
                                    "count": new_count
                                })

        db.commit()
        result = {
            "age_group": age_group,
            "gender_distribution": gender_distribution,
            "city_distribution": city_distribution
        }

        return result

    except HTTPException as e:
        db.rollback()
        traceback.print_exc()
        return JSONResponse(status_code=e.status_code, content={"error": e.detail})
    except Exception:
        db.rollback()
        traceback.print_exc()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"error": "Something went wrong."})

@router.get("/fetch_all_posts")
def fetch_all_posts(db: Session = Depends(get_db)):
    try:
        # Initialize variables to store all posts
        all_posts = []
        
        # Paginate through all posts from the Instagram API
        posts_url = f"{BASE_URL}{ZING_INSTAGRAM_ACCOUNT_ID}/media?fields=id,media_type,media_url,timestamp&access_token={ZING_ACCESS_TOKEN}"
        while posts_url:
            posts_response = requests.get(posts_url)

            if posts_response.status_code != 200:
                raise HTTPException(
                    status_code=posts_response.status_code,
                    detail=f"Failed to fetch posts: {posts_response.text}"
                )

            posts_data = posts_response.json()
            all_posts.extend(posts_data.get("data", []))
            # Check if there's a next page
            posts_url = posts_data.get("paging", {}).get("next")

        # If no posts found, return a message
        if not all_posts:
            return JSONResponse(content={"message": "No posts found."})

        # Prepare the response by fetching metrics for each post
        post_metrics = []
        for post in all_posts:
            post_id = post.get("id")
            media_type = post.get("media_type")
            media_url = post.get("media_url")
            raw_timestamp = post.get("timestamp")

            # Format timestamp
            post_created = None
            if raw_timestamp:
                utc_time = datetime.strptime(raw_timestamp, "%Y-%m-%dT%H:%M:%S%z")
                post_created = utc_time.strftime("%Y-%m-%d")
            # Check if there is an existing post for today, if so, update or skip
            existing_post = db.query(Posts).filter(
                Posts.post_id == post_id,
                func.date(Posts.created_ts) == datetime.now(timezone.utc).date()
            ).first()

            if existing_post:
                continue
            else:
                # Insert post details into `Posts` table
                db_post = Posts(
                    post_id=post_id,
                    media_type=media_type,
                    media_url=media_url,
                    post_created=post_created,
                    created_ts=datetime.now(timezone.utc)
                )
                db.add(db_post)
                db.commit()

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

            # Extract reach and saves values
            reach = None
            for insight in post_insights.get("data", []):
                if insight.get("name") == "reach":
                    reach = insight.get("values", [{}])[0].get("value")
                    break

            saves = None
            for insight in save_insights.get("data", []):
                if insight.get("name") == "saved":
                    saves = insight.get("values", [{}])[0].get("value")

           # Check for existing PostInsights record for today
            existing_insight = db.query(PostInsights).filter(
                PostInsights.posts_id == db_post.id,
                func.date(PostInsights.created_ts) == datetime.now(timezone.utc).date()
            ).first()

            if existing_insight:
                # If there's an existing insight for today, update the count
                existing_insight.reach += (reach or 0)  # Update based on new data
                existing_insight.likes += (like_count or 0)
                existing_insight.saves += (saves or 0)
            else:
                # Insert insights into `PostInsights` table
                db_insight = PostInsights(
                    posts_id=db_post.id,
                    reach=reach,
                    likes=like_count,
                    saves=saves,
                    created_ts=datetime.now(timezone.utc)
                )
                db.add(db_insight)

            db.commit()

            # Add the post details to the metrics list
            post_metrics.append({
                "post_id": post_id,
                "media_type": media_type,
                "media_url": media_url,
                "post_created": post_created,
                "reach": reach,
                "likes": like_count,
                "saves": saves
            })
        
        # Prepare the final response
        result = {
            "total_posts": len(post_metrics)
        }

        return JSONResponse(content=f"Successfully Retrieved and Added the Data Into Database {result}")

    except HTTPException as e:
        traceback.print_exc()
        return JSONResponse(status_code=e.status_code, content={"error": e.detail})
    except Exception:
        traceback.print_exc()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"error": "Something went wrong."})

# @router.get("/fetch_top_posts")
# def fetch_top_posts():
#     try:
#         global ZING_ACCESS_TOKEN
#         # Refresh the short-lived token
#         if is_access_token_expired(ZING_ACCESS_TOKEN):
#             try:
#                 refreshed_token = refresh_access_token(APP_ID, APP_SECRET, LONG_LIVED_TOKEN)
#                 set_key('.env', 'ZING_ACCESS_TOKEN', refreshed_token)
#                 load_dotenv()  # Reload the updated .env file
#                 ZING_ACCESS_TOKEN = os.getenv("ZING_ACCESS_TOKEN")  # Get updated token
#             except Exception as e:
#                 try:
#                     new_long_lived_token = generate_new_long_lived_token()
#                     set_key('.env', 'LONG_LIVED_TOKEN', new_long_lived_token)
#                     load_dotenv()  # Reload the updated .env file
#                     new_zing_access_token = refresh_access_token(APP_ID, APP_SECRET, new_long_lived_token)
#                     set_key('.env', 'ZING_ACCESS_TOKEN', new_zing_access_token)
#                     load_dotenv()  # Reload the updated .env file
#                     ZING_ACCESS_TOKEN = os.getenv("ZING_ACCESS_TOKEN")
#                 except Exception as gen_error:
#                     raise HTTPException(
#                         status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#                         detail=f"Failed to generate new long-lived token: {str(gen_error)}"
#                     )
#                 raise HTTPException(
#                     status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#                     detail=f"Failed to refresh access token: {str(e)}"
#                 )

#         # Calculate the date one month ago
#         one_month_ago = datetime.now(timezone.utc) - timedelta(days=30)

#         # Fetch top-performing posts and reels
#         posts_url = f"{BASE_URL}{ZING_INSTAGRAM_ACCOUNT_ID}/media?fields=id,media_type,media_url,timestamp&access_token={ZING_ACCESS_TOKEN}"
#         posts_response = requests.get(posts_url)

#         if posts_response.status_code != 200:
#             raise HTTPException(
#                 status_code=posts_response.status_code,
#                 detail=f"Failed to fetch posts: {posts_response.text}"
#             )
#         posts_data = posts_response.json()

#         # Filter posts from the last month
#         recent_posts = []
#         for post in posts_data.get("data", []):
#             # Convert timestamp to proper UTC format
#             raw_timestamp = post.get("timestamp")
#             if raw_timestamp:
#                 utc_time = datetime.strptime(raw_timestamp, "%Y-%m-%dT%H:%M:%S%z")
#                 formatted_utc_time = utc_time.strftime("%Y-%m-%d %H:%M:%S")
                
#                 # Add to recent posts if within the last month
#                 if utc_time >= one_month_ago:
#                     recent_posts.append({
#                         "post_id": post.get("id"),
#                         "media_type": post.get("media_type"),
#                         "media_url": post.get("media_url"),
#                         "timestamp": formatted_utc_time  # Store formatted timestamp
#                     })

#         # Count the number of recent posts
#         total_recent_posts = len(recent_posts)

#         # Extract top-performing posts and reels
#         top_posts = []
#         for post in recent_posts:
#             post_id = post.get("post_id")
#             media_type = post.get("media_type")
#             media_url = post.get("media_url")
#             post_created = post.get("timestamp")

#             if not media_url:
#                 continue

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

#             # Fetch insights for posts and reels
#             insights_url = f"{BASE_URL}{post_id}/insights?metric=reach&access_token={ZING_ACCESS_TOKEN}"
#             insights_response = requests.get(insights_url)

#             if insights_response.status_code != 200:
#                 raise HTTPException(
#                     status_code=insights_response.status_code,
#                     detail=f"Failed to fetch insights: {insights_response.text}"
#                 )
#             post_insights = insights_response.json()

#             saves_url = f"{BASE_URL}{post_id}/insights?metric=saved&access_token={ZING_ACCESS_TOKEN}"
#             saves_response = requests.get(saves_url)

#             if saves_response.status_code != 200:
#                 raise HTTPException(
#                     status_code=saves_response.status_code,
#                     detail=f"Failed to fetch saves: {saves_response.text}"
#                 )
#             save_insights = saves_response.json()

#             reach = None
#             for insight in post_insights.get("data", []):
#                 if insight.get("name") == "reach":
#                     reach = insight.get("values", [{}])[0].get("value")
#                     break
            
#             saves = None
#             for insight in save_insights.get("data", []):
#                 if insight.get("name") == "saved":
#                     saves = insight.get("values", [{}])[0].get("value")
#             if reach or like_count or saves:
#                 top_posts.append({
#                     "post_id": post_id,
#                     "media_type": media_type,
#                     "media_url": media_url,
#                     "post_created": post_created,  # Already formatted
#                     "reach": reach,
#                     "likes":like_count,
#                     "saves": saves
#                 })

#         # Sort posts by reach in descending order and take the top 5
#         top_posts = sorted(top_posts, key=lambda x: x["reach"], reverse=True)[:5]
#         result = {
#             "total_recent_posts": total_recent_posts,
#             "top_posts": top_posts
#         }
#         return JSONResponse(content=result)

#     except HTTPException as e:
#         traceback.print_exc()
#         return JSONResponse(status_code=e.status_code, content={"error": e.detail})
#     except Exception:
#         traceback.print_exc()
#         return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"error": "Something went wrong."})
    
# @router.get("/fetch_today_posts")
# def fetch_today_posts():
#     try:
#         global ZING_ACCESS_TOKEN
#         # Refresh the short-lived token
#         if is_access_token_expired(ZING_ACCESS_TOKEN):
#             try:
#                 refreshed_token = refresh_access_token(APP_ID, APP_SECRET, LONG_LIVED_TOKEN)
#                 set_key('.env', 'ZING_ACCESS_TOKEN', refreshed_token)
#                 load_dotenv()  # Reload the updated .env file
#                 ZING_ACCESS_TOKEN = os.getenv("ZING_ACCESS_TOKEN")  # Get updated token
#             except Exception as e:
#                 try:
#                     new_long_lived_token = generate_new_long_lived_token()
#                     set_key('.env', 'LONG_LIVED_TOKEN', new_long_lived_token)
#                     load_dotenv()  # Reload the updated .env file
#                     new_zing_access_token = refresh_access_token(APP_ID, APP_SECRET, new_long_lived_token)
#                     set_key('.env', 'ZING_ACCESS_TOKEN', new_zing_access_token)
#                     load_dotenv()  # Reload the updated .env file
#                     ZING_ACCESS_TOKEN = os.getenv("ZING_ACCESS_TOKEN")
#                 except Exception as gen_error:
#                     raise HTTPException(
#                         status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#                         detail=f"Failed to generate new long-lived token: {str(gen_error)}"
#                     )
#                 raise HTTPException(
#                     status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#                     detail=f"Failed to refresh access token: {str(e)}"
#                 )

#         # Get the current date to filter posts (today's date)
#         today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

#         # Fetch all posts for today
#         posts_url = f"{BASE_URL}{ZING_INSTAGRAM_ACCOUNT_ID}/media?fields=id,media_type,media_url,timestamp&access_token={ZING_ACCESS_TOKEN}"
#         posts_response = requests.get(posts_url)

#         if posts_response.status_code != 200:
#             raise HTTPException(
#                 status_code=posts_response.status_code,
#                 detail=f"Failed to fetch posts: {posts_response.text}"
#             )
#         posts_data = posts_response.json()

#         # Filter posts from today based on the timestamp
#         todays_posts = []
#         for post in posts_data.get("data", []):
#             raw_timestamp = post.get("timestamp")
#             if raw_timestamp:
#                 utc_time = datetime.strptime(raw_timestamp, "%Y-%m-%dT%H:%M:%S%z")
#                 formatted_utc_time = utc_time.strftime("%Y-%m-%d")
                
#                 # Include post if it matches today's date
#                 if formatted_utc_time == today:
#                     todays_posts.append({
#                         "post_id": post.get("id"),
#                         "media_type": post.get("media_type"),
#                         "media_url": post.get("media_url"),
#                         "timestamp": formatted_utc_time  # Store formatted timestamp
#                     })

#         if not todays_posts:
#             return JSONResponse(content={"message": "No posts found for today."})

#         # Fetch metrics for each post (reach, likes, saves)
#         post_metrics = []
#         for post in todays_posts:
#             post_id = post.get("post_id")
#             media_type = post.get("media_type")
#             media_url = post.get("media_url")
#             post_created = post.get("timestamp")

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

#             reach = None
#             for insight in post_insights.get("data", []):
#                 if insight.get("name") == "reach":
#                     reach = insight.get("values", [{}])[0].get("value")
#                     break

#             saves = None
#             for insight in save_insights.get("data", []):
#                 if insight.get("name") == "saved":
#                     saves = insight.get("values", [{}])[0].get("value")

#             post_metrics.append({
#                 "post_id": post_id,
#                 "media_type": media_type,
#                 "media_url": media_url,
#                 "post_created": post_created,  # Already formatted
#                 "reach": reach,
#                 "likes": like_count,
#                 "saves": saves
#             })

#         result = {
#             "total_posts_today": len(todays_posts),
#             "posts": post_metrics
#         }

#         return JSONResponse(content=result)

#     except HTTPException as e:
#         traceback.print_exc()
#         return JSONResponse(status_code=e.status_code, content={"error": e.detail})
#     except Exception:
#         traceback.print_exc()
#         return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"error": "Something went wrong."})
