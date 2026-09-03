import os
from flask import Blueprint, jsonify, request
from app.models.movie import Movie
from app.models.download_link import DownloadLink
from sqlalchemy import exists, and_, func
from app import db

movies_bp = Blueprint('movies', __name__, url_prefix='/api')


def has_non_youtube_link():
    """Subquery: movie has at least one non-YouTube download link."""
    return exists().where(
        and_(
            DownloadLink.movie_id == Movie.id,
            DownloadLink.host != 'YouTube'
        )
    )


@movies_bp.route('/movies/<slug>', methods=['DELETE'])
def delete_movie(slug):
    token = request.headers.get('X-Crawler-Token')
    if token != os.getenv('CRAWLER_SECRET', 'secret123'):
        return jsonify({'error': 'Unauthorized'}), 401

    movie = Movie.query.filter_by(slug=slug).first_or_404()

    # Delete download links first (foreign key)
    DownloadLink.query.filter_by(movie_id=movie.id).delete()
    db.session.delete(movie)
    db.session.commit()

    return jsonify({'status': f'Deleted: {movie.title}'}), 200


@movies_bp.route('/movies/random')
def get_random_movie():
    """One random movie, for the Telegram bot's periodic spotlight posts.
    Same non-YouTube-link rule as the main listing, so a random pick never
    surfaces a movie with nothing watchable behind it."""
    movie = (
        Movie.query
        .filter(has_non_youtube_link())
        .order_by(func.random())
        .first()
    )
    if not movie:
        return jsonify({'error': 'No movies available'}), 404
    return jsonify(movie.to_dict())


@movies_bp.route('/movies')
def get_movies():
    page  = request.args.get('page', 1, type=int)
    genre = request.args.get('genre', None)

    query = Movie.query

    if genre:
        query = query.filter(Movie.genre.ilike(f'%{genre}%'))

    # YouTube-only movies only appear under the Nollywood filter.
    # For all other feeds (no genre or any other genre), exclude them.
    is_nollywood = genre and 'nollywood' in genre.lower()
    if not is_nollywood:
        query = query.filter(has_non_youtube_link())

    # Show newest year first, then most recently added within same year
    movies = query.order_by(
        Movie.year.desc().nullslast(),
        Movie.created_at.desc()
    ).paginate(page=page, per_page=20, error_out=False)

    return jsonify({
        'movies':  [m.to_dict() for m in movies.items],
        'total':   movies.total,
        'pages':   movies.pages,
        'current': movies.page
    })


@movies_bp.route('/movies/<slug>')
def get_movie(slug):
    movie = Movie.query.filter_by(slug=slug).first_or_404()
    return jsonify(movie.to_dict())