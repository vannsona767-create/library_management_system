import os
from uuid import uuid4

from flask import Blueprint, current_app, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from app.extensions import db
from app.models import Book, Category, Borrowing
from app.routes.admin import admin_required

books_bp = Blueprint('books', __name__, url_prefix='/books')

BOOKS_PER_PAGE = 8
ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'avif'}


@books_bp.route('/')
@login_required
def list_books():
    """Browse all books, with optional search and category filtering."""
    search = request.args.get('search', '').strip()
    category_id = request.args.get('category', type=int)
    page = request.args.get('page', 1, type=int)

    query = Book.query

    if search:
        # Match against title, author, or ISBN
        like = f'%{search}%'
        query = query.filter(
            db.or_(
                Book.title.ilike(like),
                Book.author.ilike(like),
                Book.isbn.ilike(like),
            )
        )

    if category_id:
        query = query.filter_by(category_id=category_id)

    pagination = query.order_by(Book.title).paginate(
        page=page, per_page=BOOKS_PER_PAGE, error_out=False
    )

    categories = Category.query.order_by(Category.name).all()

    return render_template(
        'user/books.html',
        books=pagination.items,
        pagination=pagination,
        categories=categories,
        search=search,
        selected_category=category_id,
    )


@books_bp.route('/<int:book_id>')
@login_required
def book_detail(book_id):
    """Show full details for a single book."""
    book = Book.query.get_or_404(book_id)

    # Does this user already have a copy out? Controls which button shows.
    already_borrowed = Borrowing.query.filter(
        Borrowing.user_id == current_user.id,
        Borrowing.book_id == book.id,
        Borrowing.status.in_(['Borrowed', 'Overdue'])
    ).first() is not None

    return render_template('user/book_detail.html',
                            book=book, already_borrowed=already_borrowed)


# =====================================================================
# Admin-only book management
# =====================================================================

@books_bp.route('/manage')
@admin_required
def manage_books():
    """Admin view: table of all books with edit/delete actions."""
    search = request.args.get('search', '').strip()
    page = request.args.get('page', 1, type=int)

    query = Book.query
    if search:
        like = f'%{search}%'
        query = query.filter(
            db.or_(
                Book.title.ilike(like),
                Book.author.ilike(like),
                Book.isbn.ilike(like),
            )
        )

    pagination = query.order_by(Book.title).paginate(
        page=page, per_page=15, error_out=False
    )

    return render_template(
        'admin/books.html',
        books=pagination.items,
        pagination=pagination,
        search=search,
    )


def _validate_book_form(form, book_id=None):
    """Shared validation for add/edit. Returns (cleaned_data, errors)."""
    errors = []

    title = form.get('title', '').strip()
    author = form.get('author', '').strip()
    isbn = form.get('isbn', '').strip()
    category_id = form.get('category_id', type=int)
    description = form.get('description', '').strip()
    published_year = form.get('published_year', type=int)
    quantity = form.get('quantity', type=int)

    if not title:
        errors.append('Title is required.')
    if not author:
        errors.append('Author is required.')
    if not isbn:
        errors.append('ISBN is required.')

    if quantity is None or quantity < 0:
        errors.append('Quantity must be 0 or more.')

    if published_year is not None and (published_year < 1000 or published_year > 2100):
        errors.append('Published year must be a valid year.')

    # ISBN must be unique across other books
    if isbn:
        existing = Book.query.filter_by(isbn=isbn).first()
        if existing and existing.id != book_id:
            errors.append('A book with that ISBN already exists.')

    data = {
        'title': title,
        'author': author,
        'isbn': isbn,
        'category_id': category_id or None,
        'description': description or None,
        'published_year': published_year,
        'quantity': quantity,
    }
    return data, errors


def _save_book_image(file_storage):
    """Save an uploaded book cover and return its static-relative path."""
    if not file_storage or not file_storage.filename:
        return None

    original_name = secure_filename(file_storage.filename)
    extension = original_name.rsplit('.', 1)[-1].lower() if '.' in original_name else ''
    if extension not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValueError('Book image must be PNG, JPG, JPEG, GIF, WEBP, or AVIF.')

    upload_dir = os.path.join(current_app.static_folder, 'uploads', 'books')
    os.makedirs(upload_dir, exist_ok=True)
    filename = f'{uuid4().hex}.{extension}'
    file_storage.save(os.path.join(upload_dir, filename))
    return f'uploads/books/{filename}'


@books_bp.route('/add', methods=['GET', 'POST'])
@admin_required
def add_book():
    categories = Category.query.order_by(Category.name).all()

    if request.method == 'POST':
        data, errors = _validate_book_form(request.form)

        if errors:
            for e in errors:
                flash(e, 'error')
            return render_template('admin/add_book.html',
                                    categories=categories, form=request.form)

        try:
            image_path = _save_book_image(request.files.get('image'))
        except ValueError as error:
            flash(str(error), 'error')
            return render_template('admin/add_book.html',
                                    categories=categories, form=request.form)

        book = Book(
            title=data['title'],
            author=data['author'],
            isbn=data['isbn'],
            category_id=data['category_id'],
            description=data['description'],
            published_year=data['published_year'],
            quantity=data['quantity'],
            image=image_path,
            # A brand new book starts fully available
            available_quantity=data['quantity'],
        )
        db.session.add(book)
        db.session.commit()

        flash(f'"{book.title}" was added to the library.', 'success')
        return redirect(url_for('books.manage_books'))

    return render_template('admin/add_book.html', categories=categories, form={})


@books_bp.route('/<int:book_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_book(book_id):
    book = Book.query.get_or_404(book_id)
    categories = Category.query.order_by(Category.name).all()

    if request.method == 'POST':
        data, errors = _validate_book_form(request.form, book_id=book.id)

        # How many copies are currently out on loan?
        on_loan = book.quantity - book.available_quantity

        # Can't reduce total quantity below what's already borrowed
        if data['quantity'] is not None and data['quantity'] < on_loan:
            errors.append(
                f'Quantity cannot be less than {on_loan} - that many copies are currently borrowed.'
            )

        if errors:
            for e in errors:
                flash(e, 'error')
            return render_template('admin/edit_book.html',
                                    book=book, categories=categories, form=request.form)

        try:
            image_path = _save_book_image(request.files.get('image'))
        except ValueError as error:
            flash(str(error), 'error')
            return render_template('admin/edit_book.html',
                                    book=book, categories=categories, form=request.form)

        book.title = data['title']
        book.author = data['author']
        book.isbn = data['isbn']
        book.category_id = data['category_id']
        book.description = data['description']
        book.published_year = data['published_year']
        book.quantity = data['quantity']
        if image_path:
            book.image = image_path
        # Keep available in step with the new total, preserving copies on loan
        book.available_quantity = data['quantity'] - on_loan

        db.session.commit()

        flash(f'"{book.title}" was updated.', 'success')
        return redirect(url_for('books.manage_books'))

    return render_template('admin/edit_book.html',
                            book=book, categories=categories, form={})


@books_bp.route('/<int:book_id>/delete', methods=['POST'])
@admin_required
def delete_book(book_id):
    book = Book.query.get_or_404(book_id)

    # Refuse to delete while copies are still out on loan
    if book.available_quantity < book.quantity:
        flash('Cannot delete a book that still has copies on loan.', 'error')
        return redirect(url_for('books.manage_books'))

    title = book.title
    db.session.delete(book)
    db.session.commit()

    flash(f'"{title}" was deleted.', 'success')
    return redirect(url_for('books.manage_books'))
