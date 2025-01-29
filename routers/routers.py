import os
import traceback
import requests
from datetime import datetime, timezone, timedelta
import pymysql
from dotenv import load_dotenv, set_key
from fastapi import APIRouter,HTTPException, status
from fastapi.responses import JSONResponse
from utilities.access_token import refresh_access_token, is_access_token_expired, generate_new_long_lived_token

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
def fetch_insights_zing():
    """
    Fetch a summarized version of Instagram insights, showing only important metrics.
    Automatically refreshes access token if needed.
    """
    connection = None
    try:
        # Establish MySQL connection
        connection = pymysql.connect(
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            database=DB_NAME,
        )

        def ensure_table_exists():
            """
            Ensures the table 'socialmedia' exists in the database.
            Creates the table if it doesn't exist.
            """
            with connection.cursor() as cursor:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS zing.socialmedia (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    username VARCHAR(255),
                    followers INT,
                    impressions INT,
                    reach INT,
                    accounts_engaged INT,
                    website_clicks INT,
                    created_ts DATETIME
                );
                """)
                connection.commit()

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
        impressions, reach, accounts_engaged, period, website_clicks = None, None, None, None, None
        for item in insights_data.get("data", []):
            if item.get("name") == "impressions" and "total_value" in item:
                impressions = item["total_value"].get("value")
                period = item.get("period")
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
            "period": period,
            "impressions": impressions,
            "reach": reach,
            "accounts_engaged": accounts_engaged,
            "website_clicks" : website_clicks
        }

        # Ensure the table exists
        ensure_table_exists()

        # Begin database transaction
        with connection.cursor() as cursor:
            try:
                cursor.execute("""
                    INSERT INTO zing.socialmedia (username, followers, impressions, reach, accounts_engaged, website_clicks, created_ts)
                    VALUES (%s, %s, %s, %s, %s, %s, %s);
                """, (
                    result["username"],
                    result["followers_count"],
                    result["impressions"],
                    result["reach"],
                    result["accounts_engaged"],
                    result["website_clicks"],
                    datetime.now(timezone.utc)
                ))
                connection.commit()  # Commit changes if everything is fine
            except Exception as e:
                connection.rollback()  # Rollback if an error occurs
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to insert data into database: {str(e)}"
                )

        return JSONResponse(content=result)

    except HTTPException as e:
        traceback.print_exc()
        return JSONResponse(status_code=e.status_code, content={"error": e.detail})
    except Exception:
        traceback.print_exc()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"error": "Something went wrong."})
    finally:
        if connection:
            connection.close()

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

@router.get("/fetch_all_posts")
def fetch_all_posts():
    try:
        # Initialize variables to store all posts
        all_posts = []

         # Connect to the database
        connection = pymysql.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME
        )

        with connection.cursor() as cursor:
            # Create `Posts` table if not exists
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS zing.posts (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    post_id VARCHAR(255) NOT NULL,
                    media_type VARCHAR(50),
                    media_url TEXT,
                    post_created DATE
                )
            """)

            # Create `PostInsights` table if not exists
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS zing.postinsights (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    posts_id INT NOT NULL,
                    reach INT,
                    likes INT,
                    saves INT,
                    FOREIGN KEY (posts_id) REFERENCES posts(id) ON DELETE CASCADE
                )
            """)

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

            # Insert post details into `Posts` table
            cursor.execute("""
                INSERT INTO posts (post_id, media_type, media_url, post_created)
                VALUES (%s, %s, %s, %s)
            """, (post_id, media_type, media_url, post_created))
            post_db_id = cursor.lastrowid

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

            # Insert insights into `PostInsights` table
            cursor.execute("""
                INSERT INTO zing.postinsights (posts_id, reach, likes, saves)
                VALUES (%s, %s, %s, %s)
            """, (post_db_id, reach, like_count, saves))
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
            "total_posts": len(post_metrics),
            "posts": post_metrics
        }

        return JSONResponse(content=result)

    except HTTPException as e:
        traceback.print_exc()
        return JSONResponse(status_code=e.status_code, content={"error": e.detail})
    except Exception:
        traceback.print_exc()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"error": "Something went wrong."})