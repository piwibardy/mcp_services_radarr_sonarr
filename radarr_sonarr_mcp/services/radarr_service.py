"""Service for interacting with Radarr API."""

from dataclasses import dataclass
from typing import List, Dict, Any, Optional
import requests
from ..config import RadarrConfig


@dataclass
class Movie:
    """Movie data class."""
    id: int
    tmdb_id: int
    title: str
    year: int
    overview: str
    has_file: bool
    status: str
    tags: List[int] = None
    genres: List[str] = None
    data: Dict[str, Any] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Movie':
        """Create a Movie object from a dictionary."""
        return cls(
            id=data.get('id', 0),
            tmdb_id=data.get('tmdbId', 0),
            title=data.get('title', ''),
            year=data.get('year', 0),
            overview=data.get('overview', ''),
            has_file=data.get('hasFile', False),
            status=data.get('status', ''),
            tags=data.get('tags', []),
            genres=data.get('genres', []),
            data=data
        )


class RadarrService:
    """Service for interacting with Radarr API."""
    
    def __init__(self, config: RadarrConfig):
        """Initialize the Radarr service with configuration."""
        self.config = config
    
    def get_all_movies(self) -> List[Movie]:
        """Fetch all movies from Radarr."""
        try:
            response = requests.get(
                f"{self.config.base_url}/movie",
                params={"apikey": self.config.api_key},
                timeout=30
            )
            response.raise_for_status()
            
            movies = []
            for movie_data in response.json():
                movies.append(Movie.from_dict(movie_data))
            
            return movies
        except requests.RequestException as e:
            import logging
            logging.error(f"Error fetching movies from Radarr: {e}")
            raise Exception(f"Failed to fetch movies from Radarr: {e}")
    
    def lookup_movie(self, term: str) -> List[Movie]:
        """Look up movies by search term."""
        try:
            response = requests.get(
                f"{self.config.base_url}/movie/lookup",
                params={"term": term, "apikey": self.config.api_key},
                timeout=30
            )
            response.raise_for_status()
            
            movies = []
            for movie_data in response.json():
                movies.append(Movie.from_dict(movie_data))
            
            return movies
        except requests.RequestException as e:
            import logging
            logging.error(f"Error looking up movie in Radarr: {e}")
            raise Exception(f"Failed to lookup movie in Radarr: {e}")
    
    def get_movie_file(self, movie_id: int) -> Dict[str, Any]:
        """Get the file information for a movie."""
        try:
            response = requests.get(
                f"{self.config.base_url}/moviefile",
                params={"movieId": movie_id, "apikey": self.config.api_key},
                timeout=30
            )
            response.raise_for_status()
            
            return response.json()
        except requests.RequestException as e:
            import logging
            logging.error(f"Error fetching movie file for ID {movie_id}: {e}")
            raise Exception(f"Failed to fetch movie file: {e}")

    def get_quality_profiles(self) -> list:
        """Fetch available quality profiles from Radarr."""
        try:
            response = requests.get(
                f"{self.config.base_url}/qualityprofile",
                params={"apikey": self.config.api_key},
                timeout=30
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            import logging
            logging.error(f"Error fetching quality profiles from Radarr: {e}")
            raise Exception(f"Failed to fetch quality profiles: {e}")

    def get_root_folders(self) -> list:
        """Fetch available root folders from Radarr."""
        try:
            response = requests.get(
                f"{self.config.base_url}/rootfolder",
                params={"apikey": self.config.api_key},
                timeout=30
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            import logging
            logging.error(f"Error fetching root folders from Radarr: {e}")
            raise Exception(f"Failed to fetch root folders: {e}")

    def lookup_movie_by_tmdb(self, tmdb_id: int) -> dict:
        """Lookup a movie by TMDB ID to get full metadata."""
        try:
            response = requests.get(
                f"{self.config.base_url}/movie/lookup/tmdb",
                params={"tmdbId": tmdb_id, "apikey": self.config.api_key},
                timeout=30
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            import logging
            logging.error(f"Error looking up TMDB ID {tmdb_id}: {e}")
            raise Exception(f"Failed to lookup movie by TMDB ID: {e}")

    def add_movie(
        self,
        tmdb_id: int,
        quality_profile_id: int,
        root_folder_path: str,
        monitored: bool = True,
        search_for_movie: bool = False,
        minimum_availability: str = "announced",
        tags: list = None,
    ) -> dict:
        """Add a movie to Radarr via POST /api/v3/movie."""
        import logging
        movie_data = self.lookup_movie_by_tmdb(tmdb_id)

        payload = {
            "tmdbId": tmdb_id,
            "title": movie_data.get("title"),
            "qualityProfileId": quality_profile_id,
            "rootFolderPath": root_folder_path,
            "monitored": monitored,
            "minimumAvailability": minimum_availability,
            "year": movie_data.get("year"),
            "images": movie_data.get("images", []),
            "addOptions": {
                "searchForMovie": search_for_movie,
            },
            "tags": tags or [],
        }

        try:
            response = requests.post(
                f"{self.config.base_url}/movie",
                params={"apikey": self.config.api_key},
                json=payload,
                timeout=30
            )
            if response.status_code == 400:
                error_data = response.json()
                if any("MovieExistsValidator" in str(e) for e in error_data):
                    raise ValueError("Movie already exists in Radarr")
                raise ValueError(f"Bad request: {error_data}")
            response.raise_for_status()
            result = response.json()
            return {
                "success": True,
                "movie_id": result.get("id", 0),
                "title": result.get("title"),
                "path": result.get("path"),
                "message": "Movie added successfully",
            }
        except ValueError:
            raise
        except requests.RequestException as e:
            logging.error(f"Error adding movie {tmdb_id} to Radarr: {e}")
            raise Exception(f"Failed to add movie: {e}")

    def is_movie_watched(self, movie: Movie) -> bool:
        """Check if a movie is watched based on tags."""
        # This is an assumption - actual implementation may vary based on how
        # watched status is tracked in your Radarr setup
        return movie.data.get('movieFile', {}).get('mediaInfo', {}).get('watched', False)

    def is_movie_in_watchlist(self, movie: Movie) -> bool:
        """Check if a movie is in the watchlist based on tags."""
        # This is an assumption - implementation may vary
        # Assuming 'watchlist' tag with ID 1 (adjust as needed)
        return 1 in (movie.tags or [])
