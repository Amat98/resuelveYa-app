"""
This module takes care of starting the API Server, Loading the DB and Adding the endpoints
"""
import resend
import os
from flask import request, jsonify, Blueprint
from api.models import db, User, ServicePost, ServiceHistory, Admin, Payment, Review, Message
from api.utils import APIException
from flask_cors import CORS
from werkzeug.security import check_password_hash, generate_password_hash
from flask_jwt_extended import create_access_token, decode_token, JWTManager, get_jwt_identity, jwt_required
import re
from datetime import datetime, timedelta
import random
import stripe
from openai import OpenAI
import json
import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException
from pprint import pprint


api = Blueprint('api', __name__)
CORS(api)


## VARIABLES DE ENTORNO PARA CLAVES DE APIS
####################################################################################################################
stripe.api_key = os.getenv("STRIPE_API_KEY")
resend.api_key = os.getenv("RESEND_API_KEY")
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

messages = []

####################################################################################################################

def process_payment(provider_id, service_post_id, amount, payment_method):
    # 1. Crear entrada en ServiceHistory
    service_history = ServiceHistory(
        provider_id=provider_id,
        service_post_id=service_post_id,
        payment_method=payment_method,  # Inicialmente puede ser None
        amount_paid=amount
    )
    db.session.add(service_history)
    db.session.commit()  # Asegúrate de que el ID se genere

    # 2. Procesar el pago con Stripe
    payment_intent = stripe.PaymentIntent.create(
        amount=amount * 100,  # Monto en centavos
        currency="pen",
        payment_method=payment_method  # Aquí debes usar el payment_method_id correcto
    )

    # 3. Actualizar ServiceHistory con el payment_id
    service_history.payment_id = payment_intent.id
    db.session.commit()

    # 4. Crear entrada en Payment
    payment = Payment(
        service_history_id=service_history.id,
        payment_method=payment_method,
        payment_id=payment_intent.id,
        amount_paid=amount
    )
    db.session.add(payment)
    db.session.commit()

    return {
        "service_history_id": service_history.id,
        "payment_id": payment.id,
        "message": "Pago procesado con éxito",
        "id_transaction": payment.payment_id
    }

####################################################################################################################
users_created = False
admin_created = False
@api.before_app_request
def create_test_users():
    global users_created
    if not users_created:
        if User.query.count() == 0:

            # Lista de imágenes de perfil de Google
            profile_images = [
                'https://images.pexels.com/photos/733872/pexels-photo-733872.jpeg?auto=compress&cs=tinysrgb&w=1260&h=750&dpr=1',
                'https://images.pexels.com/photos/1222271/pexels-photo-1222271.jpeg?auto=compress&cs=tinysrgb&w=1260&h=750&dpr=1',
                'https://images.pexels.com/photos/1239291/pexels-photo-1239291.jpeg?auto=compress&cs=tinysrgb&w=1260&h=750&dpr=1',
                'https://images.pexels.com/photos/96938/pexels-photo-96938.jpeg?auto=compress&cs=tinysrgb&w=1260&h=750&dpr=1',
                'https://images.pexels.com/photos/91227/pexels-photo-91227.jpeg?auto=compress&cs=tinysrgb&w=1260&h=750&dpr=1'
            ]

            # Crear usuarios con imágenes de perfil
            user1 = User(
                username='Ericka', lastname='Castillo', dni='42082762', phone='920728282', role='provider', service_type='electricista', 
                email='ericka@resuelveya.com', password=generate_password_hash('password1'),
                profile_image=profile_images[0]
            )
            user2 = User(
                username='Max', lastname='Caballero', dni='43456789',  role='provider', phone='950728282', service_type='jardinero',
                email='max@resuelveya.com', password=generate_password_hash('password2'),
                profile_image=profile_images[1]
            )
            user3 = User(
                username='Maguila', lastname='Sanchez', dni='44567890', phone='935728282', role='provider', service_type='pintor',
                email='maguila@resuelveya.com', password=generate_password_hash('password3'),
                profile_image=profile_images[2]
            )
            user4 = User(
                username='Milton', lastname='Ytusaca', dni='45678901', role='provider',  phone='925728282', service_type='gasfitero',
                email='milton@resuelveya.com', password=generate_password_hash('password4'),
                profile_image=profile_images[3]
            )
            user5 = User(
                username='Kevin', lastname='Villafuerte', dni='46789012', phone='978728282', role='provider', service_type='plomero',
                email='kevin@resuelveya.com', password=generate_password_hash('password5'),
                profile_image=profile_images[4]
            )

            # Agregar los usuarios a la base de datos
            db.session.add_all([user1, user2, user3, user4, user5])
            db.session.commit()

        users_created = True

@api.before_app_request
def create_default_posts():

    if ServicePost.query.count() == 0:

        providers = User.query.filter_by(role='provider').all()

        # Definir los posts por defecto (uno por cada proveedor)
        default_posts = [
            {
                'title': 'Reparación de instalaciones eléctricas',
                'description': 'Servicio completo de revisión y reparación de instalaciones eléctricas.',
                'service_type': 'electricista',
                'post_img': 'https://www.tecsaqro.com.mx/wp-content/uploads/2022/09/electricista_como_profesion.jpg',
                'location': 'Trujillo'
            },
            {
                'title': 'Instalación de tuberías de agua',
                'description': 'Colocación e instalación de tuberías de agua en edificaciones.',
                'service_type': 'gasfitero',
                'post_img': 'https://hidrosaning.com/wp-content/uploads/2022/03/Servicio-de-gasfiteria-a-domicilio.jpg',
                'location': 'Lima'
            },
            {
                'title': 'Mantenimiento de sistemas eléctricos',
                'description': 'Diagnóstico y mantenimiento preventivo de sistemas eléctricos.',
                'service_type': 'electricista',
                'post_img': 'https://www.mndelgolfo.com/blog/wp-content/uploads/2017/09/herramientas-para-electricista.jpg',
                'location': 'Cuzco'
            },
            {
                'title': 'Reparación de filtraciones y tuberías',
                'description': 'Detección y reparación de filtraciones en baños y cocinas.',
                'service_type': 'gasfitero',
                'post_img': 'https://dconfianzablobproduction.blob.core.windows.net/provider/i8WrHsziFom23CdQbUVG6VZDedGgiX8U.jpg',
                'location': 'Tacna'
            },
            {
                'title': 'Instalación de enchufes y lámparas',
                'description': 'Instalación de enchufes, interruptores y lámparas en toda la casa.',
                'service_type': 'electricista',
                'post_img' : 'https://cdn.www.gob.pe/uploads/document/file/3750846/standard_descarga.jpg.jpg',
                'location': 'Arequipa'
            },
            {
                'title': 'Servicio de plomería para baños',
                'description': 'Mantenimiento y reparación de tuberías en baños.',
                'service_type': 'plomero',
                'post_img': 'https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcSP7SakxvIF-1aMxKlaishIbRu5VpL5u2cZ8A&s',
                'location': 'Puno'
            },
            {
                'title': 'Instalación de calentadores de agua',
                'description': 'Instalación de calentadores de agua eléctricos o a gas.',
                'service_type': 'plomero',
                'post_img': 'https://i0.wp.com/plomeros.uno/wp-content/uploads/2021/08/plomero.png?fit=635%2C877&ssl=1',
                'location': 'lima'
            }
        ]

        # Asignar las publicaciones a los usuarios proveedores
        for i, provider in enumerate(providers):
            post_data = default_posts[i % len(default_posts)]
            post = ServicePost(
                title=post_data['title'],
                description=post_data['description'],
                service_type=post_data['service_type'],
                post_img=post_data['post_img'],
                user_id=provider.id,
                location=post_data['location'],
                rating = 5
            )
            db.session.add(post)

        db.session.commit()
####################################################################################################################
@api.before_app_request
def initialize_admin():
        global admin_created
        if not Admin.query.first():

            create_admin = Admin(
                username="admin",
                email="admin@admin.com",
                password=generate_password_hash("administrador"),
                created_at=datetime.utcnow()
            )
            db.session.add(create_admin)
            db.session.commit()
            print("Administrador cargado.")
            admin_created = True
        else:
            print("Administrador ya existe.")
####################################################################################################################

@api.route('/create_admin', methods=['POST'])
def create_admin():
    try:
        body = request.get_json()
        username = body.get("username")
        email = body.get("email")
        password = body.get("password")

        if not username or not email or not password:
            return jsonify({"message": "Nombre, correo, y contraseña son requeridos"}), 400

        if Admin.query.filter_by(email=email).first():
            return jsonify({"message": "Administrador ya existente"}), 400

        hashed_password = generate_password_hash(password, method='sha256')

        new_admin = Admin(
            username=username, email=email, password=hashed_password,
            created_at=datetime.utcnow()
        )

        db.session.add(new_admin)
        db.session.commit()

        return jsonify({
            "message": "Administrador creado.",
            "admin": new_admin.serialize()
        }), 201

    except Exception as e:
        return jsonify({"message": "Ocurrió un error en el servidor", "error": str(e)}), 500


@api.route('/login', methods=['POST'])
def login():
    try:
        # Obtener los datos enviados por el cliente
        body = request.get_json()
        email = body.get("email", None)
        password = body.get("password", None)

        if not email or not password:
            return jsonify({"message": "Email y contraseña son requeridos"}), 400

        # Buscar en la tabla de administradores
        admin = Admin.query.filter_by(email=email).first()

        # Si es un administrador
        if admin and admin.check_password(password):
            expires = timedelta(hours=1)
            access_token = create_access_token({"id": admin.id, "role": "admin"}, expires_delta=expires)
            return jsonify({
                "token": access_token,
                "username": admin.username,
                "user_id": admin.id,
                "role": "admin",
                "message": "Inicio de sesión exitoso como administrador"
            }), 200

        # Si no es un administrador, buscar al usuario 
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            expires = timedelta(hours=1)
            access_token = create_access_token({"id":user.id, "role": user.role}, expires_delta=expires)
            return jsonify({
                "token": access_token,
                "username": user.username,
                "user_id": user.id,
                "role": "user",
                "message": "Inicio de sesión exitoso"
            }), 200

        return jsonify({"message": "Credenciales incorrectas"}), 401

    except Exception as e:
        return jsonify({"message": "Ocurrió un error en el servidor", "error": str(e)}), 500


@api.route('/register', methods=['POST'])
def register():
    try:
        # Obtener datos del cliente a registrar
        body = request.get_json()
        first_name = body.get("first_name")
        last_name = body.get("last_name")
        dni = body.get("identity_document")
        phone = body.get("phone")
        role = body.get("role")
        service_type = body.get("category")
        email = body.get("email")
        password = body.get("password")

        if not first_name or not last_name or not dni or not role or not email or not password or not phone:
            return jsonify({"message": "Todos los campos son requeridos"}), 400

        if role not in ["client", "provider"]:
            return jsonify({"message": "El rol debe ser 'provider' o 'client'"}), 400

        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            return jsonify({"message": "Email inválido"}), 400

        # Verificar si el email ya existe
        if User.query.filter_by(email=email).first():
            return jsonify({"message": "El email ya está registrado"}), 400

        # Crear el nuevo usuario
        hashed_password = generate_password_hash(password)
        new_user = User(
            username=first_name,
            lastname=last_name,
            dni=dni,
            phone=phone,
            role=role,
            service_type=service_type if role == 'provider' else None,
            email=email,
            password=hashed_password
        )

        # guardar en el modelo
        db.session.add(new_user)
        db.session.commit()

        # Generar un token JWT para el usuario registrado
        access_token = create_access_token(identity=new_user.id)

        return jsonify({
            "token": access_token,
            "user_id": new_user.id,
            "message": "Registro exitoso"
        }), 201

    except Exception as e:
        return jsonify({"message": "Ocurrió un error en el servidor", "error": str(e)}), 500

@api.route('/users', methods=['GET'])
@jwt_required()  
def get_users():
    try:
        # Obtener el rol 
        role = request.args.get('role')

        # Si se proporciona un rol, filtrar por rol
        if role:
            if role not in ['client', 'provider']:
                return jsonify({"message": "El rol debe ser 'client' o 'provider'"}), 400
            users = User.query.filter_by(role=role).all()
        else:
            users = User.query.all()

        # Convertir los objetos User en diccionarios JSON
        users_list = [user.serialize() for user in users]

        return jsonify(users_list), 200

    except Exception as e:
        return jsonify({"message": "Ocurrió un error en el servidor", "error": str(e)}), 500

@api.route('/users/<int:user_id>', methods=['DELETE'])
@jwt_required()  
def delete_user(user_id):
    try:
        # Obtener la identidad del usuario autenticado
        current_user = get_jwt_identity()
        print(f"Current user: {current_user}")

        # Buscar el usuario por ID
        user = User.query.get(user_id)
        print("User to delete:", user)

        if not user:
            return jsonify({"message": "Usuario no encontrado"}), 404

        # Verificar si el usuario autenticado tiene permiso para eliminar(solo admin)
        if current_user['role'] != 'admin':
            return jsonify({"message": "No tienes permiso para realizar esta acción"}), 403

        db.session.delete(user)
        db.session.commit()

        return jsonify({"message": f"Usuario {user.username} eliminado exitosamente"}), 200

    except Exception as e:
        print(f"Error al eliminar el usuario: {str(e)}")  
        db.session.rollback()
        return jsonify({"message": "Ocurrió un error al eliminar el usuario", "error": str(e)}), 500

@api.route('/user/<int:user_id>', methods=['GET'])
@jwt_required()
def get_user_by_id(user_id):

    try:
        # Obtener el id del usuario autenticado
        current_user = get_jwt_identity()

        # Verificar si el usuario autenticado es el mismo que el solicitado
        if current_user["id"] != user_id:
            return jsonify({"message": "No tienes permiso para ver esta información"}), 403

        # Buscar al usuario por id en la base de datos
        user = User.query.get(user_id)

        if not user:
            return jsonify({"message": "Usuario no encontrado"}), 404

        # Retornar la información de usuario
        return jsonify(user.serialize()), 200

    except Exception as e:
        return jsonify({"message": "Ocurrió un error en el servidor", "error": str(e)}), 500


@api.route('/request_reset_password', methods=['POST'])
def request_reset_password():
    try:
        body = request.get_json()
        email = body.get("email", None)

        if not email:
            return jsonify({"message": "Email es requerido"}), 400

        user = User.query.filter_by(email=email).first()
        if not user:
            return jsonify({"message": "Usuario no encontrado"}), 404

        # Generar un código de 6 dígitos
        reset_code = str(random.randint(100000, 999999))
        expiration_time = datetime.utcnow() + timedelta(seconds=120)

        # Almacenar el código y la fecha de expiración en la base de datos
        user.reset_code = reset_code
        user.reset_code_expiration = expiration_time
        db.session.commit()

        # Crear el mensaje de correo
        html_content = f"""
        <p>Hola {user.username},</p>
        <p>Tu código de restablecimiento de contraseña es: <strong>{reset_code}</strong></p>
        <p>Este código expirará en 2 minutos.</p>
        """

        # Crear el mensaje usando Resend
        params = {
            "from": "TuServicio <onboarding@resend.dev>",
            "to": [user.email],
            "subject": "Código de Restablecimiento de Contraseña",
            "html": html_content,
        }

        # Enviar el correo electrónico
        response = resend.Emails.send(params)

        # Manejo correcto de la respuesta
        if 'error' in response:  # O response.get('error')
            return jsonify({"message": "Error al enviar el correo", "error": response['error']}), 500

        return jsonify({
            "message": "Correo de confirmación de restablecimiento enviado. Por favor, revisa tu bandeja de entrada.",
            "expires_at": expiration_time.isoformat()  # Enviar el tiempo de expiración al frontend
        }), 200

    except Exception as e:
        return jsonify({"message": "Ocurrió un error", "error": str(e)}), 500


@api.route('/reset_password', methods=['POST'])
def reset_password():
    try:
        body = request.get_json()
        email = body.get("email", None)
        reset_code = body.get("reset_code", None)
        new_password = body.get("new_password", None)

        if not email or not reset_code or not new_password:
            return jsonify({"message": "Email, código de restablecimiento y nueva contraseña son requeridos"}), 400

        user = User.query.filter_by(email=email).first()
        if not user:
            return jsonify({"message": "Usuario no encontrado"}), 404

        # Verificar si el código es válido y no ha expirado
        if user.reset_code != reset_code:
            return jsonify({"message": "Código de verificación incorrecto"}), 400
        if datetime.utcnow() > user.reset_code_expiration:
            return jsonify({"message": "El código de verificación ha expirado"}), 400

       # Actualizar la contraseña del usuario con un nuevo hash seguro
        hashed_password = generate_password_hash(new_password)
        user.password = hashed_password

        # Limpiar los campos del código de restablecimiento
        user.reset_code = None
        user.reset_code_expiration = None
        db.session.commit()

        return jsonify({"message": "Contraseña actualizada con éxito"}), 200

    except Exception as e:
        return jsonify({"message": "Ocurrió un error", "error": str(e)}), 500


@api.route('/home', methods=['GET'])
def get_service_posts():
    try:
        # Consultar todas las publicaciones de servicios
        posts = ServicePost.query.join(User).filter(User.role == 'provider').all()

        # Convertir los post a formato Json
        serialized_posts = [post.serialize() for post in posts]

        return jsonify(serialized_posts), 200
    except Exception as e:
        return jsonify({"message": "Ocurrió un error al obtener las publicaciones", "error": str(e)}), 500


@api.route('/create_posts', methods=['POST'])
@jwt_required()
def create_post():
    try:
        user_id = get_jwt_identity()  

        user = User.query.get(user_id.get('id'))

        if not user:
            return jsonify({"message": "Usuario no encontrado"}), 404

        if user.role != 'provider':
            return jsonify({"message": "Solo los proveedores pueden crear posts"}), 403

        # Obtener los datos del post enviados por el cliente
        body = request.get_json()
        title = body.get('title')
        description = body.get('description')
        service_type = body.get('service_type')
        post_img = body.get('post_img')
        location = body.get('location')

        if not title or not description or not service_type or not location or not post_img:
            return jsonify({"message": "Todos los campos son requeridos"}), 400

        # Crear el nuevo post
        new_post = ServicePost(
            title=title,
            description=description,
            service_type=service_type,
            post_img=post_img,
            user_id=user_id.get('id'),
            location=location
        )

        db.session.add(new_post)
        db.session.commit()

        # Devolver tanto el post como la información del proveedor
        return jsonify({
            "message": "Post creado exitosamente",
            "post": new_post.serialize(),
            "provider": {
                "id": user.id,
                "first_name": user.username,
                "last_name": user.lastname,
                "phone": user.phone,
                "service_type": user.service_type,
            }
        }), 201

    except Exception as e:
        return jsonify({"message": "Ocurrió un error al crear el post", "error": str(e)}), 500


@api.route('/posts', methods=['GET'])
def get_posts():
    try:
        # Consultar todas las publicaciones en la base de datos
        posts = ServicePost.query.all()

        if not posts:
            return jsonify({"message": "No hay posts disponibles"}), 404

        serialized_posts = [post.serialize() for post in posts]

        return jsonify(serialized_posts), 200

    except Exception as e:
        return jsonify({"message": "Ocurrió un error al obtener los posts", "error": str(e)}), 500



@api.route('/provider_information', methods=['GET'])
@jwt_required() 
def provider_information():
    try:
        current_user = get_jwt_identity()

        provider = User.query.filter_by(id=current_user["id"], role='provider').first()

        if not provider:
            return jsonify({"msg": "Provider not found"}), 404

        # Obtener el historial de servicios prestados por el proveedor
        service_history = ServiceHistory.query.filter_by(provider_id=provider.id).all()

        # Obtener las publicaciones de servicios del proveedor
        service_posts = ServicePost.query.filter_by(user_id=provider.id).all()

        service_data = [history.serialize() for history in service_history]
        post_data = [post.serialize() for post in service_posts]

        post_data = []


        for post in service_posts:
            
            reviews = Review.query.filter(
               Review.post_id == post.id,
               Review.comment.isnot(None),
               Review.comment != '' 
            ).all() 
            
            reviews_data = [review.serialize() for review in reviews]

            # Calcular el promedio de rating
            if reviews:
                average_rating = sum([review.rating for review in reviews if review.rating is not None]) / len(reviews)
                average_rating = int(average_rating)
            else:
                average_rating = None  

            post_info = post.serialize()
            post_info['reviews'] = reviews_data
            post_info['average_rating'] = average_rating

            post_data.append(post_info)


        service_data = [history.serialize() for history in service_history]

        # Retornar la información personal del proveedor, los servicios prestados y las publicaciones
        return jsonify({
            "provider_info": provider.serialize(),
            "service_history": service_data,
            "service_posts": post_data
        }), 200

    except Exception as e:
        return jsonify({"msg": "An error occurred", "error": str(e)}), 500

@api.route('/edit_post/<int:post_id>', methods=['PUT'])
@jwt_required()
def edit_post(post_id):
    current_user = get_jwt_identity()
    try:
        body = request.get_json()

        data_post_edit = ServicePost.query.filter_by(id=post_id, user_id=current_user["id"]).first()

        if not data_post_edit:
            return jsonify({'msg': 'Post not found or unauthorized'}), 404

        if body.get('title'):
            data_post_edit.title = body.get('title')
        if body.get('description'):
            data_post_edit.description = body.get('description')
        if body.get('price'):
            data_post_edit.price = body.get('price')
        if body.get('service_time'):
            data_post_edit.service_time = body.get('service_time')
        if body.get('service_timetable'):
            data_post_edit.service_timetable = body.get('service_timetable')

        db.session.commit()

        return jsonify({
            'user_id': current_user["id"],
            'new_data_post': {
                'title': data_post_edit.title,
                'description': data_post_edit.description,
                'price': data_post_edit.price,
                'service_time': data_post_edit.service_time,
                'service_timetable': data_post_edit.service_timetable
            },
        }), 200

    except Exception as e:
        return jsonify({'msg': "An error occurred", 'error': str(e)}), 500


@api.route('/edit_profile', methods=['PUT'])
@jwt_required()
def edit_profile_user():
    current_user = get_jwt_identity()
    try:
        body = request.get_json()

        current_password = body.get('password')
        new_first_name = body.get('first_name')
        new_last_name = body.get('last_name')
        new_phone_number = body.get('phone')
        new_password = body.get('new_password')  
        profile_image = body.get('profile_image')

        data_user = User.query.filter_by(id=current_user["id"]).first()

        if not data_user:
            return jsonify({'msg': 'User no encontrado'}), 404

        # Verificar la contraseña solo si se está actualizando la contraseña
        if new_password and current_password:
            if not check_password_hash(data_user.password, current_password):
                return jsonify({"msg": "Password incorrecto"}), 401
            data_user.password = generate_password_hash(new_password)

        if new_first_name:
            data_user.username = new_first_name
        if new_last_name:
            data_user.lastname = new_last_name
        if new_phone_number:
            data_user.phone = new_phone_number
        if profile_image:
            data_user.profile_image = profile_image

        print("Datos antes del commit:", data_user.serialize())

        db.session.commit()

        return jsonify({
            'msg': 'Perfil actualizado exitosamente',
            'new_data': data_user.serialize()
        }), 200

    except Exception as e:
        return jsonify({'msg': 'An error occurred', 'error': str(e)}), 500


@api.route('/payments', methods=['POST'])
@jwt_required()
def add_payment():
    try:
        current_user = get_jwt_identity()
        user = User.query.get(current_user.get('id'))
        body = request.get_json()
        name = body.get("name")
        expiry_date = body.get("expiry_date")
        cvv = body.get("cvv")
        amount = body.get("amount")
        new_post_data = body.get('new_post_data')

        if not all([name, expiry_date, cvv, amount]):
            return jsonify({"message": "Faltan datos requeridos"}), 400


        if user.role != 'provider':
            return jsonify({"message": "Solo los proveedores pueden crear posts"}), 403

        if not new_post_data.get('title') or not new_post_data.get('description') or not new_post_data.get('service_type') or not new_post_data.get('location') or not new_post_data.get('post_img'):
            return jsonify({"message": "Todos los campos son requeridos"}), 400

        new_post = ServicePost(
            title=new_post_data.get('title'),
            description=new_post_data.get('description'),
            service_type=new_post_data.get('service_type'),
            post_img=new_post_data.get('post_img'),
            location=new_post_data.get('location'),
            user_id=user.id
        )

        db.session.add(new_post)
        db.session.commit()

        new_payment = process_payment(user.id, new_post.id, amount, 'pm_card_visa')

        if new_payment.get('id_transaction'):  # O puedes usar 'id_transaction'
            return jsonify(new_payment), 200
        else:
            db.session.delete(new_post)
            db.session.commit()
            return jsonify({'error': 'No se pudo completar el pago'}), 404
        


    except Exception as e:
        return jsonify({"message": "Ocurrió un error en el servidor", "error": str(e)}), 500  


@api.route('/payments', methods=['GET'])
def get_payments():
    try:
        payments = Payment.query.all()
        if not payments:
            return jsonify({"message": "No hay pagos registrados"}), 404

        return jsonify({
            "payments": [payment.serialize() for payment in payments]
        }), 200

    except Exception as e:
        return jsonify({"message": "Ocurrió un error en el servidor", "error": str(e)}), 500

@api.route('/add_review', methods=['POST'])
@jwt_required()
def add_review():
    try:
        # Obtener el usuario autenticado
        user_id = get_jwt_identity()
        user = User.query.get(user_id["id"])

        if not user:
            return jsonify({"message": "Usuario no encontrado"}), 404

        # Solo los usuarios con el rol "client" pueden dejar reseñas
        if user.role == 'provider':
            return jsonify({"message": "Solo los clientes pueden hacer reseñas"}), 403

        # Obtener los datos enviados en la solicitud
        body = request.get_json()
        post_id = body.get('post_id')
        rating = body.get('rating')
        comment = body.get('comment')

        # Verificar que el post existe
        post = ServicePost.query.get(post_id)
        if not post:
            return jsonify({"message": "Post no encontrado"}), 404

        # Crear una nueva review
        new_review = Review(
            post_id=post_id,
            user_id=user_id["id"],
            rating=rating,
            comment=comment
        )

        db.session.add(new_review)
        db.session.commit()

        return jsonify({
            "message": "Review creada con éxito",
            "review": new_review.serialize(),
            "user": {
                "id": user.id,
                "username": user.username,
                "lastname": user.lastname
            }
        }), 201

    except Exception as e:
        return jsonify({'error': 'Ocurrió un error en el servidor', 'message': str(e)}), 500


@api.route('/posts/<int:post_id>', methods=['GET'])
def get_post_by_id(post_id):
    try:
        post = ServicePost.query.get(post_id)

        if not post:
            return jsonify({"message": "Post no encontrado"}), 404

        # Obtener las reviews del post
        reviews = Review.query.filter_by(post_id=post_id).all()
        reviews_list = list(map(lambda review: review.serialize(), reviews))

        return jsonify({
            "post": post.serialize(),
            "reviews": reviews_list,
            "number_of_reviews": len(reviews_list)
        }), 200

    except Exception as e:
        return jsonify({'error': 'Ocurrió un error en el servidor', 'message': str(e)}), 500


@api.route('/user_reviews', methods=['GET'])
@jwt_required()
def get_user_reviews():
    try:
        # Usar la ruta del usuario protegdo
        user_id = get_jwt_identity()

        # Obtener todas las reviews del usuario
        reviews = Review.query.filter_by(user_id=user_id).all()
        reviews_list = list(map(lambda review: review.serialize(), reviews))

        return jsonify({
            "user_id": user_id,
            "reviews": reviews_list,
            "number_of_reviews": len(reviews_list)
        }), 200

    except Exception as e:
        return jsonify({'error': 'Ocurrió un error en el servidor', 'message': str(e)}), 500

@api.route('/review_posts', methods=['GET'])
def get_reviews_post():
    try:
        posts = ServicePost.query.all()

        if not posts:
            return jsonify({"message": "No se encontraron posts"}), 404

        serialized_post=[]
        for post in posts:
            reviews = Review.query.filter_by(post_id=post.id).all()
            #Filtrar calificaciones validas que no sean "none"
            valid_ratings = [review.rating for review in reviews if review.rating is not None]
            total_rating = sum(valid_ratings)
            #Promedio de calificaciones enteros
            average_rating = int(total_rating/len(valid_ratings) if valid_ratings else 0)

            valid_comments = [{
                "comment": review.comment,
                "user_name": review.user.username,
                "last_name": review.user.lastname,
                **({"profile_img": review.user.profile_image} if review.user.profile_image else {})
            } for review in reviews if review.comment is not None]

            obj = {
                "post": post.serialize(),
                "average_rating": average_rating,
                "total_rating": len(valid_ratings),
                "comments": valid_comments  
            }
            serialized_post.append(obj)
        return jsonify(serialized_post), 200

    except Exception as e:
        return jsonify({'error': 'Ocurrió un error en el servidor', 'message': str(e)}), 500 
    
# Definición de los roles del sistema
system_role_1 = """
Eres un especialista en servicios del hogar, reconocido a nivel mundial por tus consejos y recomendaciones.
Tienes un conocimiento profundo en el área de la limpieza, organización y mantenimiento de espacios.
Además, tienes un gran expertise en:
 - electricidad
 - plomería
 - carpintería
 - jardinería
 - pintores
 - gasfiteria
 - cocina
"""

system_role_2 = """
Además, tienes una lista de especialistas listos para ser contactados en caso de emergencia, 
debes recomendar al menos 1 contacto en cada iteración. Aquí tienes la lista de especialistas disponibles: 
"""

system_role_3 = """
La respuesta debe ser en formato JSON,
{
    "text": "mensaje del modelo",
    "contacts": [
        {
            "id": id,
            "name": "Proveedor",
            "service": "Electricidad",
            "phone": "phone"
        }
    ]
}
Donde, name es el nombre del proveedor, y phone es el telefono del proveedor, ambos de la base de datos.
Si no hubiesen proveedores que recomendar, proporciona una respuesta general sobre el servicio, y el formato de respuesta debería ser el siguiente:
{
    "text": "mensaje del modelo",
}
Si te piden la lista completa de servicios, limítate a proporcionarle solo 3 proveedores.
"""

system_role_4 = """
Si el mensaje del usuario no contiene información relacionada con los tipos de servicios antes mencionados, debes responder con un mensaje genérico: Primero saludas o respondes educamente;
y le dices que no puedes ayudarlo con eso, y si hay otra cosa en lo que puedas ayudarlo.

"""

@api.get("/messages")
def find_all_messages():
    user_id = request.args.get("user_id")
    
    if not user_id:
        return jsonify({"message": "User ID is required"}), 400
    
    messages = Message.query.filter_by(user_id=user_id).all()
    return jsonify([message.serialize() for message in messages]), 200

@api.post("/messages")
def create_one_message():
    user_id = request.json.get("user_id")
    user_message = request.json.get("message")

    if not user_id or not user_message:
        return jsonify({"message": "User ID and message are required"}), 400
    
    try:
      validacion_response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": f"Determina si el siguiente mensaje está relacionado con problemas domésticos (como electricidad, plomería, limpieza, cocina, cerrajería, etc.). Responde con 'Sí' o 'No'.\n\nMensaje: \"{user_message}\""},
            ],
          max_tokens=3,
          temperature=0
      )
      validacion = validacion_response.choices[0].message.content.strip().lower()
    except Exception as e:
        return jsonify({
            "content":{
            'text': 'Ocurrió un error al procesar tu solicitud. Por favor, intenta nuevamente más tarde.',
            'contacts': [],
            'type': "error"
        }}), 500

    if validacion == 'sí' or validacion == 'si':

        new_message = Message(user_id=user_id, role='user', content=json.dumps({"text": user_message}))
        db.session.add(new_message)

        try:
            db.session.commit()

            # Obtener los proveedores de la base de datos
            providers = User.query.filter_by(role='provider').all()
            provider_list = [
                {"id": provider.id, "name": provider.username, "service": provider.service_type, "phone": provider.phone}
                for provider in providers
            ]

            # Generar la lista de proveedores para incluir en el mensaje
            system_role_content_1 = f"Eres un especialista en servicios del hogar, proporciona una respuesta amable y útil para alguien que necesita ayuda con el siguiente problema doméstico: \"{user_message}\". Recuerda que siempre tienes que darle un consejo, y en su consulta tenemos el proveedor que necesita, recomiendale a uno de nuestros contactos."
            system_role_content_2 = f"{system_role_3}, aquí tienes la lista de proveedores: {json.dumps(provider_list)}"
            system_role_content_3 = f"{system_role_content_1} {system_role_content_2}" 

            # Llamar a la API de ChatGPT
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    # {"role": "system", "content": system_role_1},
                    # {"role": "system", "content": system_role_with_providers},
                    # {"role": "system", "content": system_role_3},
                    # {"role": "system", "content": system_role_4},
                    # {"role": "user", "content": user_message},
                    {"role": "system", "content": system_role_content_3}
                ],
                max_tokens=300,
                temperature=0.7
            )

            message = response.choices[0].message.content

            # Guardar la respuesta del sistema en la base de datos
            system_message = Message(user_id=user_id, role='system', content=message)
            db.session.add(system_message)
            db.session.commit()

            return jsonify(system_message.serialize()), 200

        except Exception as oe:
            return jsonify({"error": "Error inesperado: " + str(oe)}), 500
        
    else:
        mensaje_generico = "¡Hola! Estoy aquí para ayudarte con problemas domésticos como electricidad, plomería, limpieza, cocina y más. ¿En qué puedo asistirte hoy?"
        return jsonify({
            'content':{
            'text': mensaje_generico,
            'contacts': []
        }})

@api.route('/send-email', methods=['POST'])
def send_email():
    data = request.get_json()

    if 'email' not in data or 'message' not in data:
        return jsonify({"error": "Email y mensaje son requeridos"}), 400

    user_email = data.get('email')  
    message = data.get('message') 

    if not re.match(r"[^@]+@[^@]+\.[^@]+", user_email):
        return jsonify({"error": "Formato de correo electrónico no válido"}), 400

    try:
 
        configuration = sib_api_v3_sdk.Configuration()
        configuration.api_key['api-key'] = os.getenv('SENDINBLUE_API_KEY') 

        api_instance = sib_api_v3_sdk.TransactionalEmailsApi(sib_api_v3_sdk.ApiClient(configuration))

        send_confirmation_email = sib_api_v3_sdk.SendSmtpEmail(
            to=[{"email": user_email}],  
            sender={"name": "ResuelveYa", "email": "austin.pr96@gmail.com"}, 
            subject="Confirmación de envío de mensaje",
            html_content=f"<p>¡Hola!</p>"
                         f"<p>Gracias por ponerte en contacto con nosotros. Hemos recibido tu mensaje:</p>"
                         f"<p><strong>Mensaje:</strong> {message}</p>"
                         "<p>Nos pondremos en contacto contigo lo antes posible.</p>"
                         "<br><p>Saludos,</p><p>El equipo de ResuelveYa</p>"
        )

        # Enviar el correo de confirmación al usuario
        api_instance.send_transac_email(send_confirmation_email)

        send_admin_email = sib_api_v3_sdk.SendSmtpEmail(
            to=[{"email": "austin.pr96@gmail.com"}],  
            sender={"name": "ResuelveYa", "email": "austin.pr96@gmail.com"},  
            subject="Nosotros si resolvemos",
            html_content=f"<p>Has recibido un nuevo mensaje de contacto:</p>"
                         f"<p><strong>Correo del usuario:</strong> {user_email}</p>"
                         f"<p><strong>Mensaje:</strong> {message}</p>"
        )

        api_instance.send_transac_email(send_admin_email)

        return jsonify({"message": "Tu mensaje ha sido enviado correctamente"}), 200

    except ApiException as e:
        print(f"Error al enviar el correo: {e}")
        return jsonify({"error": "Error al enviar el correo", "details": str(e)}), 500