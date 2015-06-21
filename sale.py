from flask import Blueprint, render_template, current_app, abort, g, \
    url_for, request, session, redirect, flash, jsonify
from galatea.tryton import tryton
from galatea.helpers import login_required, customer_required, manager_required
from galatea.csrf import csrf
from flask.ext.babel import gettext as _, lazy_gettext, ngettext
from flask.ext.paginate import Pagination
from trytond.transaction import Transaction

sale = Blueprint('sale', __name__, template_folder='templates')

DISPLAY_MSG = lazy_gettext('Displaying <b>{start} - {end}</b> of <b>{total}</b>')

SHOP = current_app.config.get('TRYTON_SALE_SHOP')
SHOPS = current_app.config.get('TRYTON_SALE_SHOPS')
LIMIT = current_app.config.get('TRYTON_PAGINATION_SALE_LIMIT', 20)
LIMIT_WISHLIST = current_app.config.get('TRYTON_PAGINATION_WISHLIST_LIMIT', 20)
LIMIT_LAST_PRODUCTS = current_app.config.get('TRYTON_PAGINATION_LAST_PRODUCTS_LIMIT', 20)
LIMIT_TOTAL_LAST_PRODUCTS = current_app.config.get('TRYTON_TOTAL_LAST_PRODUCTS_LIMIT', 200)
STATE_EXCLUDE = current_app.config.get('TRYTON_SALE_STATE_EXCLUDE', [])

Sale = tryton.pool.get('sale.sale')
SaleWishlist = tryton.pool.get('sale.wishlist')
Cart = tryton.pool.get('sale.cart')
Product = tryton.pool.get('product.product')
GalateaUser = tryton.pool.get('galatea.user')

SALE_STATES_TO_CANCEL =['draft', 'quotation']

@sale.route("/admin/<int:id>", endpoint="admin-sale")
@manager_required
@tryton.transaction()
def admin_sale_detail(lang, id):
    '''Admin Sale Detail'''
    sales = Sale.search([
        ('id', '=', id),
        ], limit=1)
    if not sales:
        abort(404)

    sale, = Sale.browse(sales)

    #breadcumbs
    breadcrumbs = [{
        'slug': url_for('admin', lang=g.language),
        'name': _('Admin'),
        }, {
        'slug': url_for('.admin-sales', lang=g.language),
        'name': _('Sales'),
        }, {
        'slug': url_for('.admin-sale', lang=g.language, id=sale.id),
        'name': sale.reference or _('Not reference'),
        }]

    return render_template('admin/sale.html',
            breadcrumbs=breadcrumbs,
            sale=sale,
            )

@sale.route("/admin/cancel/", methods=["POST"], endpoint="admin-cancel")
@manager_required
@csrf.exempt
@tryton.transaction()
def admin_sale_cancel(lang):
    '''Admin Sale Cancel'''
    id = request.form.get('id')
    if not id:
        flash(_('Error when cancel. Select a sale to cancel.'), "danger")

    sales = Sale.search([
        ('id', '=', id),
        ], limit=1)
    if not sales:
        flash(_('Error when cancel. You not have permisions to cancel.'), "danger")

    sale, = sales
    Sale.cancel([sale])
    flash(_('Sale "%s" was cancelled.' % (sale.rec_name)))

    return redirect(url_for('.admin-sale', id=id, lang=g.language))

@sale.route("/admin/", endpoint="admin-sales")
@manager_required
@tryton.transaction()
def admin_sale_list(lang):
    '''Admin Sales'''

    try:
        page = int(request.args.get('page', 1))
    except ValueError:
        page = 1

    domain = []
    q = request.args.get('q')
    if q:
        domain.append(('rec_name', 'ilike', '%'+q+'%'))
    party = request.args.get('party')
    if party:
        domain.append(('party', 'ilike', '%'+party+'%'))
    
    total = Sale.search_count(domain)
    offset = (page-1)*LIMIT

    order = [
        ('sale_date', 'DESC'),
        ('id', 'DESC'),
        ]
    sales = Sale.search(domain, offset, LIMIT, order)

    pagination = Pagination(
        page=page, total=total, per_page=LIMIT, display_msg=DISPLAY_MSG, bs_version='3')

    #breadcumbs
    breadcrumbs = [{
        'slug': url_for('admin', lang=g.language),
        'name': _('Admin'),
        }, {
        'slug': url_for('.admin-sales', lang=g.language),
        'name': _('Sales'),
        }]

    return render_template('admin/sales.html',
            breadcrumbs=breadcrumbs,
            pagination=pagination,
            sales=sales,
            q=q,
            party=party,
            )

@sale.route("/<int:id>", endpoint="sale")
@tryton.transaction()
def sale_detail(lang, id):
    '''Sale Detail

    Not required login decorator because create new sale
    anonymous users (not loggin in)
    '''
    customer = session.get('customer')
    if not session.get('logged_in'):
        session.pop('customer', None)

    sales = Sale.search([
        ('id', '=', id),
        ('shop', 'in', SHOPS),
        ('party', '=', customer),
        ('state', 'not in', STATE_EXCLUDE),
        ], limit=1)
    if not sales:
        abort(404)

    sale, = Sale.browse(sales)

    #breadcumbs
    breadcrumbs = [{
        'slug': url_for('my-account', lang=g.language),
        'name': _('My Account'),
        }, {
        'slug': url_for('.sales', lang=g.language),
        'name': _('Sales'),
        }, {
        'slug': url_for('.sale', lang=g.language, id=sale.id),
        'name': sale.reference or _('Not reference'),
        }]

    return render_template('sale.html',
            breadcrumbs=breadcrumbs,
            sale=sale,
            )

@sale.route("/cancel/", methods=["POST"], endpoint="cancel")
@login_required
@customer_required
@tryton.transaction()
def sale_cancel(lang):
    '''Sale Cancel'''
    id = request.form.get('id')
    if not id:
        flash(_('Error when cancel. Select a sale to cancel.'), "danger")

    sales = Sale.search([
        ('id', '=', id),
        ('shop', 'in', SHOPS),
        ('party', '=', session['customer']),
        ], limit=1)
    if not sales:
        flash(_('Error when cancel. You not have permisions to cancel.'), "danger")

    sale, = sales
    if sale.state in SALE_STATES_TO_CANCEL:
        Sale.cancel([sale])
        flash(_('Sale "%s" was cancelled.' % (sale.rec_name)))
    else:
        flash(_('Error when cancel "%s". Your sale is in a state that not available ' \
            'to cancel. Contact Us.' % (sale.rec_name)), "danger")

    return redirect(url_for('.sale', id=id, lang=g.language))

@sale.route("/", endpoint="sales")
@login_required
@customer_required
@tryton.transaction()
def sale_list(lang):
    '''Sales'''

    try:
        page = int(request.args.get('page', 1))
    except ValueError:
        page = 1

    domain = [
        ('shop', 'in', SHOPS),
        ('party', '=', session['customer']),
        ('state', 'not in', STATE_EXCLUDE),
        ]
    total = Sale.search_count(domain)
    offset = (page-1)*LIMIT

    order = [
        ('sale_date', 'DESC'),
        ('id', 'DESC'),
        ]
    sales = Sale.search(domain, offset, LIMIT, order)

    pagination = Pagination(
        page=page, total=total, per_page=LIMIT, display_msg=DISPLAY_MSG, bs_version='3')

    #breadcumbs
    breadcrumbs = [{
        'slug': url_for('my-account', lang=g.language),
        'name': _('My Account'),
        }, {
        'slug': url_for('.sales', lang=g.language),
        'name': _('Sales'),
        }]

    return render_template('sales.html',
            breadcrumbs=breadcrumbs,
            pagination=pagination,
            sales=sales,
            )


@sale.route("/last-products", endpoint="last-products")
@login_required
@customer_required
@tryton.transaction()
def last_products(lang):
    '''Last products'''
    user = GalateaUser(session['user'])

    shipment_address = 'AND s.shipment_address=%s' % user.shipment_address.id  \
            if user.shipment_address else ''

    # TODO Filter product esale
    query = """
        SELECT
          DISTINCT(s.product)
        FROM (
            SELECT
              l.product FROM sale_sale s, sale_line l
            WHERE
              s.id = l.sale AND l.product IS NOT NULL AND s.party=%(customer)s %(shipment_address)s
            ORDER BY
              l.create_date DESC
            ) s
        LIMIT %(limit)s;
        """ % {
            'customer': session['customer'],
            'shipment_address': shipment_address,
            'limit': LIMIT_TOTAL_LAST_PRODUCTS,
        }
    cursor = Transaction().cursor
    cursor.execute(query)
    results = [x[0] for x in cursor.fetchall()]

    # Get products from schema results
    try:
        page = int(request.args.get('page', 1))
    except ValueError:
        page = 1

    limit = LIMIT_LAST_PRODUCTS

    total = len(results)
    offset = (page-1)*LIMIT_LAST_PRODUCTS

    domain = [('id', 'in', results)]
    last_products = Product.search(domain, offset, limit)

    pagination = Pagination(page=page, total=total, per_page=limit, display_msg=DISPLAY_MSG, bs_version='3')

    breadcrumbs = [{
        'slug': url_for('my-account', lang=g.language),
        'name': _('My Account'),
        }, {
        'slug': url_for('.sales', lang=g.language),
        'name': _('Sales'),
        }, {
        'name': _('Last Products'),
        }]

    return render_template('sale-last-products.html',
        products=last_products,
        pagination=pagination,
        breadcrumbs=breadcrumbs,
    )

@sale.route('/wishlist/add', methods=['POST'], endpoint="wishlist-add")
@csrf.exempt
@login_required
@customer_required
@tryton.transaction()
def wishlist_add(lang):
    '''Add Wishlist products'''
    success = []
    warning = []

    ids = set()
    for data in request.json:
        if data.get('name'):
            prod = data.get('name').split('-')
            try:
                ids.add(int(prod[1]))
            except:
                continue

    ids = list(ids)
    if not ids:
        return jsonify(result=False)

    domain = [
        ('id', 'in', ids),
        ('esale_available', '=', True),
        ('esale_active', '=', True),
        ('shops', 'in', [SHOP]),
        ]
    products = Product.search(domain)

    domain = [
        ('party', '=', session['customer']),
        ('product', 'in', products),
        ]
    wishlists = SaleWishlist.search(domain)
    repeat_products = [w.product for w in wishlists]

    to_create = []
    for product in products:
        if product in repeat_products:
            warning.append(
                _('%(product)s already exists in your account.' % {
                    'product': product.rec_name,
                    }),
                )
            continue
        to_create.append({
            'party': session['customer'],
            'quantity': 1,
            'product': product,
            })

    if to_create:
        SaleWishlist.create(to_create)
        success.append(ngettext(
            '%(num)s product has been added in your account.',
            '%(num)s products have been added in your account.',
            len(to_create)))

    messages = {}
    messages['success'] = ",".join(success)
    messages['warning'] = ",".join(warning)

    return jsonify(result=True, messages=messages)

@sale.route("/wishlist", methods=["GET", "POST"], endpoint="wishlist")
@csrf.exempt
@login_required
@customer_required
@tryton.transaction()
def wishlist(lang):
    '''Wishlist products'''
    if request.method == 'POST':
        # Delete wishlists
        removes = request.form.getlist('remove')
        if removes:
            removes = list(set(int(r) for r in removes))
            to_remove = SaleWishlist.search([
                ('party', '=', session['customer']),
                ('id', 'in', removes),
                ])
            if to_remove:
                SaleWishlist.delete(to_remove)
                flash(ngettext(
                    '%(num)s wishlist has been deleted in your account.',
                    '%(num)s wishlists have been deleted in your account.',
                    len(to_remove)), 'success')

    try:
        page = int(request.args.get('page', 1))
    except ValueError:
        page = 1

    limit = LIMIT_WISHLIST

    domain = [
        ('party', '=', session['customer']),
        ('product.esale_available', '=', True),
        ('product.esale_active', '=', True),
        ('product.shops', 'in', [SHOP]),
        ]

    total = SaleWishlist.search_count(domain)
    offset = (page-1)*limit

    wishlists = SaleWishlist.search(domain, offset, limit)

    pagination = Pagination(page=page, total=total, per_page=limit, display_msg=DISPLAY_MSG, bs_version='3')

    breadcrumbs = [{
        'slug': url_for('my-account', lang=g.language),
        'name': _('My Account'),
        }, {
        'slug': url_for('.sales', lang=g.language),
        'name': _('Sales'),
        }, {
        'name': _('Wishlist'),
        }]

    return render_template('sale-wishlist.html',
        wishlists=wishlists,
        pagination=pagination,
        breadcrumbs=breadcrumbs,
    )
