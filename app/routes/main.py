from flask import Blueprint, render_template
from sqlalchemy.exc import SQLAlchemyError

from app.models import Book

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
def index():
    try:
        featured_books = Book.query.order_by(Book.created_at.desc()).limit(8).all()
    except SQLAlchemyError:
        featured_books = []

    return render_template('home.html', featured_books=featured_books)
