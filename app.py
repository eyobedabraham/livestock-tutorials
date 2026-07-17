import os
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_from_directory
from werkzeug.utils import secure_filename
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'a-very-secret-key-change-me')
app.config['UPLOAD_FOLDER'] = 'static/uploads/tutorials'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin123')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ==================== DATABASE ====================
def init_db():
    conn = sqlite3.connect('tutorials.db')
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        slug TEXT NOT NULL UNIQUE
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS courses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category_id INTEGER,
        title TEXT NOT NULL,
        description TEXT,
        image TEXT,
        "order" INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (category_id) REFERENCES categories (id) ON DELETE SET NULL
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS modules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        course_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        "order" INTEGER DEFAULT 0,
        FOREIGN KEY (course_id) REFERENCES courses (id) ON DELETE CASCADE
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS lessons (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        module_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        content TEXT,
        youtube_url TEXT,
        pdf_filename TEXT,
        photo_filenames TEXT,
        "order" INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (module_id) REFERENCES modules (id) ON DELETE CASCADE
    )''')

    for cat in ['Cows', 'Goats', 'Sheep', 'Dairy Processing', 'General Farming']:
        slug = cat.lower().replace(' ', '-')
        c.execute('INSERT OR IGNORE INTO categories (name, slug) VALUES (?, ?)', (cat, slug))

    conn.commit()
    conn.close()

init_db()

# ==================== AUTH ====================
def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated

# ==================== PUBLIC ROUTES ====================
@app.route('/')
def index():
    category_filter = request.args.get('category', '')
    search_query = request.args.get('search', '')

    conn = sqlite3.connect('tutorials.db')
    conn.row_factory = sqlite3.Row
    categories = conn.execute('SELECT * FROM categories ORDER BY name').fetchall()

    query = '''SELECT courses.*, categories.name as category_name
               FROM courses LEFT JOIN categories ON courses.category_id = categories.id WHERE 1=1'''
    params = []
    if category_filter:
        query += ' AND categories.slug = ?'
        params.append(category_filter)
    if search_query:
        query += ' AND (courses.title LIKE ? OR courses.description LIKE ?)'
        params.extend([f'%{search_query}%', f'%{search_query}%'])
    query += ' ORDER BY courses."order" ASC'
    courses = conn.execute(query, params).fetchall()
    conn.close()
    return render_template('index.html', courses=courses, categories=categories,
                           current_category=category_filter, search_query=search_query)

@app.route('/course/<int:course_id>')
def course_detail(course_id):
    conn = sqlite3.connect('tutorials.db')
    conn.row_factory = sqlite3.Row
    course = conn.execute('SELECT * FROM courses WHERE id = ?', (course_id,)).fetchone()
    if not course:
        conn.close()
        return "Course not found", 404
    modules = conn.execute('SELECT * FROM modules WHERE course_id = ? ORDER BY "order"', (course_id,)).fetchall()
    module_lessons = {}
    for m in modules:
        lessons = conn.execute('SELECT * FROM lessons WHERE module_id = ? ORDER BY "order"', (m['id'],)).fetchall()
        module_lessons[m['id']] = lessons
    conn.close()
    return render_template('course.html', course=course, modules=modules, module_lessons=module_lessons)

@app.route('/lesson/<int:lesson_id>')
def lesson_view(lesson_id):
    conn = sqlite3.connect('tutorials.db')
    conn.row_factory = sqlite3.Row
    lesson = conn.execute('SELECT * FROM lessons WHERE id = ?', (lesson_id,)).fetchone()
    if not lesson:
        conn.close()
        return "Lesson not found", 404
    module = conn.execute('SELECT * FROM modules WHERE id = ?', (lesson['module_id'],)).fetchone()
    course = conn.execute('SELECT * FROM courses WHERE id = ?', (module['course_id'],)).fetchone()
    conn.close()
    return render_template('lesson.html', lesson=lesson, module=module, course=course)

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# ==================== ADMIN ROUTES ====================
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASSWORD:
            session['admin_logged_in'] = True
            flash('Logged in.', 'success')
            return redirect(url_for('admin_dashboard'))
        flash('Wrong password.', 'danger')
    return render_template('admin/login.html')

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    flash('Logged out.', 'info')
    return redirect(url_for('admin_login'))

@app.route('/admin')
@admin_required
def admin_dashboard():
    conn = sqlite3.connect('tutorials.db')
    conn.row_factory = sqlite3.Row
    stats = {
        'categories': conn.execute('SELECT COUNT(*) as n FROM categories').fetchone()['n'],
        'courses': conn.execute('SELECT COUNT(*) as n FROM courses').fetchone()['n'],
        'modules': conn.execute('SELECT COUNT(*) as n FROM modules').fetchone()['n'],
        'lessons': conn.execute('SELECT COUNT(*) as n FROM lessons').fetchone()['n']
    }
    conn.close()
    return render_template('admin/dashboard.html', stats=stats)

# Categories
@app.route('/admin/categories')
@admin_required
def admin_categories():
    conn = sqlite3.connect('tutorials.db')
    conn.row_factory = sqlite3.Row
    categories = conn.execute('SELECT * FROM categories ORDER BY name').fetchall()
    conn.close()
    return render_template('admin/categories.html', categories=categories)

@app.route('/admin/categories/add', methods=['POST'])
@admin_required
def admin_add_category():
    name = request.form.get('name', '').strip()
    slug = name.lower().replace(' ', '-')
    conn = sqlite3.connect('tutorials.db')
    try:
        conn.execute('INSERT INTO categories (name, slug) VALUES (?, ?)', (name, slug))
        conn.commit()
        flash('Category added.', 'success')
    except sqlite3.IntegrityError:
        flash('Category already exists.', 'danger')
    finally:
        conn.close()
    return redirect(url_for('admin_categories'))

@app.route('/admin/categories/delete/<int:cat_id>')
@admin_required
def admin_delete_category(cat_id):
    conn = sqlite3.connect('tutorials.db')
    conn.execute('DELETE FROM categories WHERE id = ?', (cat_id,))
    conn.commit()
    conn.close()
    flash('Category deleted.', 'info')
    return redirect(url_for('admin_categories'))

# Courses
@app.route('/admin/courses')
@admin_required
def admin_courses():
    conn = sqlite3.connect('tutorials.db')
    conn.row_factory = sqlite3.Row
    courses = conn.execute('''SELECT courses.*, categories.name as cat_name
                             FROM courses LEFT JOIN categories ON courses.category_id = categories.id
                             ORDER BY courses."order"''').fetchall()
    categories = conn.execute('SELECT * FROM categories ORDER BY name').fetchall()
    conn.close()
    return render_template('admin/courses.html', courses=courses, categories=categories)

@app.route('/admin/courses/add', methods=['POST'])
@admin_required
def admin_add_course():
    title = request.form.get('title')
    description = request.form.get('description', '')
    category_id = request.form.get('category_id') or None
    order = int(request.form.get('order', 0))
    image_filename = None
    if 'image' in request.files:
        file = request.files['image']
        if file and file.filename and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            image_filename = filename
    conn = sqlite3.connect('tutorials.db')
    conn.execute('INSERT INTO courses (title, description, category_id, image, "order") VALUES (?, ?, ?, ?, ?)',
                 (title, description, category_id, image_filename, order))
    conn.commit()
    conn.close()
    flash('Course added.', 'success')
    return redirect(url_for('admin_courses'))

@app.route('/admin/courses/edit/<int:course_id>', methods=['GET', 'POST'])
@admin_required
def admin_edit_course(course_id):
    conn = sqlite3.connect('tutorials.db')
    conn.row_factory = sqlite3.Row
    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description', '')
        category_id = request.form.get('category_id') or None
        order = int(request.form.get('order', 0))
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                conn.execute('UPDATE courses SET image = ? WHERE id = ?', (filename, course_id))
        conn.execute('UPDATE courses SET title=?, description=?, category_id=?, "order"=? WHERE id=?',
                     (title, description, category_id, order, course_id))
        conn.commit()
        conn.close()
        flash('Course updated.', 'success')
        return redirect(url_for('admin_courses'))
    course = conn.execute('SELECT * FROM courses WHERE id = ?', (course_id,)).fetchone()
    categories = conn.execute('SELECT * FROM categories ORDER BY name').fetchall()
    conn.close()
    return render_template('admin/edit_course.html', course=course, categories=categories)

@app.route('/admin/courses/delete/<int:course_id>')
@admin_required
def admin_delete_course(course_id):
    conn = sqlite3.connect('tutorials.db')
    course = conn.execute('SELECT image FROM courses WHERE id = ?', (course_id,)).fetchone()
    if course and course[0]:
        try: os.remove(os.path.join(app.config['UPLOAD_FOLDER'], course[0]))
        except OSError: pass
    conn.execute('DELETE FROM courses WHERE id = ?', (course_id,))
    conn.commit()
    conn.close()
    flash('Course deleted.', 'info')
    return redirect(url_for('admin_courses'))

# Modules
@app.route('/admin/courses/<int:course_id>/modules')
@admin_required
def admin_modules(course_id):
    conn = sqlite3.connect('tutorials.db')
    conn.row_factory = sqlite3.Row
    course = conn.execute('SELECT * FROM courses WHERE id = ?', (course_id,)).fetchone()
    modules = conn.execute('SELECT * FROM modules WHERE course_id = ? ORDER BY "order"', (course_id,)).fetchall()
    conn.close()
    return render_template('admin/modules.html', course=course, modules=modules)

@app.route('/admin/modules/add', methods=['POST'])
@admin_required
def admin_add_module():
    course_id = request.form.get('course_id')
    title = request.form.get('title')
    order = int(request.form.get('order', 0))
    conn = sqlite3.connect('tutorials.db')
    conn.execute('INSERT INTO modules (course_id, title, "order") VALUES (?, ?, ?)', (course_id, title, order))
    conn.commit()
    conn.close()
    flash('Module added.', 'success')
    return redirect(url_for('admin_modules', course_id=course_id))

@app.route('/admin/modules/edit/<int:module_id>', methods=['GET', 'POST'])
@admin_required
def admin_edit_module(module_id):
    conn = sqlite3.connect('tutorials.db')
    conn.row_factory = sqlite3.Row
    if request.method == 'POST':
        title = request.form.get('title')
        order = int(request.form.get('order', 0))
        conn.execute('UPDATE modules SET title=?, "order"=? WHERE id=?', (title, order, module_id))
        conn.commit()
        module = conn.execute('SELECT course_id FROM modules WHERE id=?', (module_id,)).fetchone()
        conn.close()
        flash('Module updated.', 'success')
        return redirect(url_for('admin_modules', course_id=module['course_id']))
    module = conn.execute('SELECT * FROM modules WHERE id = ?', (module_id,)).fetchone()
    conn.close()
    return render_template('admin/edit_module.html', module=module)

@app.route('/admin/modules/delete/<int:module_id>')
@admin_required
def admin_delete_module(module_id):
    conn = sqlite3.connect('tutorials.db')
    module = conn.execute('SELECT course_id FROM modules WHERE id=?', (module_id,)).fetchone()
    if module:
        conn.execute('DELETE FROM modules WHERE id = ?', (module_id,))
        conn.commit()
    conn.close()
    flash('Module deleted.', 'info')
    return redirect(url_for('admin_modules', course_id=module[0]))

# Lessons
@app.route('/admin/modules/<int:module_id>/lessons')
@admin_required
def admin_lessons(module_id):
    conn = sqlite3.connect('tutorials.db')
    conn.row_factory = sqlite3.Row
    module = conn.execute('SELECT * FROM modules WHERE id = ?', (module_id,)).fetchone()
    lessons = conn.execute('SELECT * FROM lessons WHERE module_id = ? ORDER BY "order"', (module_id,)).fetchall()
    conn.close()
    return render_template('admin/lessons.html', module=module, lessons=lessons)

@app.route('/admin/lessons/add', methods=['POST'])
@admin_required
def admin_add_lesson():
    module_id = request.form.get('module_id')
    title = request.form.get('title')
    content = request.form.get('content', '')
    youtube_url = request.form.get('youtube_url', '')
    order = int(request.form.get('order', 0))
    pdf_filename = None
    if 'pdf' in request.files:
        file = request.files['pdf']
        if file and file.filename and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            pdf_filename = filename
    photo_filenames = []
    if 'photos' in request.files:
        for file in request.files.getlist('photos'):
            if file and file.filename and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                photo_filenames.append(filename)
    conn = sqlite3.connect('tutorials.db')
    conn.execute('''INSERT INTO lessons (module_id, title, content, youtube_url, pdf_filename, photo_filenames, "order")
                    VALUES (?, ?, ?, ?, ?, ?, ?)''',
                 (module_id, title, content, youtube_url, pdf_filename, ','.join(photo_filenames), order))
    conn.commit()
    conn.close()
    flash('Lesson added.', 'success')
    return redirect(url_for('admin_lessons', module_id=module_id))

@app.route('/admin/lessons/edit/<int:lesson_id>', methods=['GET', 'POST'])
@admin_required
def admin_edit_lesson(lesson_id):
    conn = sqlite3.connect('tutorials.db')
    conn.row_factory = sqlite3.Row
    if request.method == 'POST':
        title = request.form.get('title')
        content = request.form.get('content', '')
        youtube_url = request.form.get('youtube_url', '')
        order = int(request.form.get('order', 0))
        if 'pdf' in request.files:
            file = request.files['pdf']
            if file and file.filename and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                conn.execute('UPDATE lessons SET pdf_filename = ? WHERE id = ?', (filename, lesson_id))
        if 'photos' in request.files:
            files = request.files.getlist('photos')
            if files and any(f.filename for f in files):
                photo_filenames = []
                for file in files:
                    if file and file.filename and allowed_file(file.filename):
                        filename = secure_filename(file.filename)
                        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                        photo_filenames.append(filename)
                conn.execute('UPDATE lessons SET photo_filenames = ? WHERE id = ?', (','.join(photo_filenames), lesson_id))
        conn.execute('UPDATE lessons SET title=?, content=?, youtube_url=?, "order"=? WHERE id=?',
                     (title, content, youtube_url, order, lesson_id))
        conn.commit()
        lesson = conn.execute('SELECT module_id FROM lessons WHERE id=?', (lesson_id,)).fetchone()
        conn.close()
        flash('Lesson updated.', 'success')
        return redirect(url_for('admin_lessons', module_id=lesson['module_id']))
    lesson = conn.execute('SELECT * FROM lessons WHERE id = ?', (lesson_id,)).fetchone()
    conn.close()
    return render_template('admin/edit_lesson.html', lesson=lesson)

@app.route('/admin/lessons/delete/<int:lesson_id>')
@admin_required
def admin_delete_lesson(lesson_id):
    conn = sqlite3.connect('tutorials.db')
    lesson = conn.execute('SELECT module_id, pdf_filename, photo_filenames FROM lessons WHERE id=?', (lesson_id,)).fetchone()
    if lesson:
        if lesson[1]:
            try: os.remove(os.path.join(app.config['UPLOAD_FOLDER'], lesson[1]))
            except OSError: pass
        if lesson[2]:
            for f in lesson[2].split(','):
                if f.strip():
                    try: os.remove(os.path.join(app.config['UPLOAD_FOLDER'], f.strip()))
                    except OSError: pass
        conn.execute('DELETE FROM lessons WHERE id = ?', (lesson_id,))
        conn.commit()
        module_id = lesson[0]
    conn.close()
    flash('Lesson deleted.', 'info')
    return redirect(url_for('admin_lessons', module_id=module_id))

if __name__ == '__main__':
    app.run(debug=True, port=5001)
