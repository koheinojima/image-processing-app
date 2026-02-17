import os
import io
import time
import requests
import numpy as np
import cv2
import collections
from datetime import datetime
from PIL import Image, ImageOps

# Google Auth
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
import gspread

# Scopes required for Drive and Sheets
SCOPES = [
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/spreadsheets'
]

class ImageProcessor:
    def __init__(self, config, credentials_data=None):
        self.config = config
        self.credentials_data = credentials_data
        self.logs = []
        self.status = "idle"
        self.status_message = "待機中"
        self.service_drive = None
        self.service_sheets = None
        self.face_detector = None
        self.last_process_log = ""
        self.result_links = None
        self.processed_count = 0
        self.total_files = 0
        self.stop_requested = False

    def log(self, message):
        timestamp = datetime.now().strftime('%H:%M:%S')
        full_msg = f"[{timestamp}] {message}"
        print(full_msg)
        self.logs.append(full_msg)
        self.status_message = message

    def authenticate(self):
        """Authenticates with Google using passed credentials or local file."""
        creds = None
        
        if self.credentials_data:
            creds = Credentials(**self.credentials_data)
        
        # Fallback to local file if no creds passed (legacy/local mode)
        if not creds:
            if os.path.exists('token.json'):
                creds = Credentials.from_authorized_user_file('token.json', SCOPES)
            
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    try:
                        creds.refresh(Request())
                    except Exception as e:
                        self.log(f"Token refresh failed: {e}")
                
                if not creds:
                    if not os.path.exists('credentials.json') and not self.credentials_data:
                        raise Exception("認証情報が見つかりません。セッションが切れている可能性があります。")
                    
                    if os.path.exists('credentials.json'):
                        flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
                        creds = flow.run_local_server(port=0)
                # Save the credentials for the next run (only in local mode)
                with open('token.json', 'w') as token:
                    token.write(creds.to_json())

        self.service_drive = build('drive', 'v3', credentials=creds)
        self.service_sheets = gspread.authorize(creds)
        self.log("認証に成功しました。")

    def download_dnn_models(self):
        filename = "face_detection_yunet_2023mar.onnx"
        url = "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
        if not os.path.exists(filename):
            self.log(f"顔検出モデルをダウンロード中: {filename}...")
            try:
                r = requests.get(url, timeout=30)
                r.raise_for_status()
                with open(filename, 'wb') as f:
                    f.write(r.content)
                self.log("モデルのダウンロードが完了しました。")
            except Exception as e:
                self.log(f"モデルのダウンロードに失敗しました: {e}")
                raise
        return filename

    def detect_faces_yunet(self, pil_img):
        img_cv = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
        h, w, _ = img_cv.shape

        if self.face_detector is None:
             model_path = self.download_dnn_models()
             self.face_detector = cv2.FaceDetectorYN.create(
                model=model_path,
                config="",
                input_size=(w, h),
                score_threshold=0.65,
                nms_threshold=0.3,
                top_k=5000
            )
        else:
             self.face_detector.setInputSize((w, h))

        _, faces = self.face_detector.detect(img_cv)

        results = []
        if faces is not None:
            min_face_size = int(min(w, h) * 0.02)
            for face in faces:
                box_x, box_y, box_w, box_h = face[0:4]
                if box_w > min_face_size and box_h > min_face_size:
                    results.append([int(box_x), int(box_y), int(box_w), int(box_h)])

        return results

    def process_logo_smart(self, img, target_w, target_h, safe_area=0.8, fmt="PNG"):
        img = ImageOps.exif_transpose(img)
        orig_w, orig_h = img.size
        
        # Whitespace crop
        bbox = img.getbbox()
        if bbox:
            img = img.crop(bbox)
            crop_info = f"余白カット({orig_w}x{orig_h}→{img.size[0]}x{img.size[1]})"
        else:
            crop_info = "余白カットなし"

        # Transparency check
        is_transparent = (img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info))
        
        if is_transparent and fmt.upper() == "PNG":
            canvas_mode = "RGBA"
            bg_color = (0, 0, 0, 0)
            bg_log = "透明"
        else:
            canvas_mode = "RGB"
            bg_color = self.get_edge_most_common_color(img, is_logo=True)
            if len(bg_color) == 4:
                bg_color = bg_color[:3]
                
            # Fallback to white only if color detection fails completely
            if not bg_color:
                 bg_color = (255, 255, 255)
            bg_log = str(bg_color)

        self.last_process_log = f"【ロゴ配置】{crop_info} / 採用背景色:{bg_log}"

        res = Image.new(canvas_mode, (target_w, target_h), bg_color)
        
        sw, sh = int(target_w * safe_area), int(target_h * safe_area)
        if img.width > 0 and img.height > 0:
            ratio = min(sw / img.width, sh / img.height)
            new_w, new_h = int(img.width * ratio), int(img.height * ratio)
            img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
            
            mask = img if img.mode == 'RGBA' else None
            res.paste(img, ((target_w - new_w) // 2, (target_h - new_h) // 2), mask)
            
        return res

    def get_edge_most_common_color(self, img, is_logo=True):
        tmp_img = img.convert("RGB")
        pixels = np.array(tmp_img)
        # Handle case where image might be too small
        if pixels.shape[0] < 2 or pixels.shape[1] < 2:
             return (255, 255, 255)
             
        top = pixels[0, :]; bottom = pixels[-1, :]; left = pixels[:, 0]; right = pixels[:, -1]
        edge_pixels = np.concatenate([top, bottom, left, right])

        if is_logo:
            pixel_tuples = [tuple(p) for p in edge_pixels]
            if not pixel_tuples: return (255, 255, 255)
            most_common = collections.Counter(pixel_tuples).most_common(1)[0][0]
            r, g, b = most_common
            if r > 248 and g > 248 and b > 248: return (255, 255, 255)
            if r < 7 and g < 7 and b < 7: return (0, 0, 0)
            return most_common
        else:
            edge_pixels = (edge_pixels // 16) * 16
            pixel_tuples = [tuple(p) for p in edge_pixels]
            if not pixel_tuples: return (0, 0, 0)
            return collections.Counter(pixel_tuples).most_common(1)[0][0]

    def calculate_safe_zone(self, faces, img_w, img_h):
        if not faces: return None
        all_x = [f[0] for f in faces]; all_y = [f[1] for f in faces]
        all_r = [f[0] + f[2] for f in faces]; all_b = [f[1] + f[3] for f in faces]

        ux1, uy1, ux2, uy2 = min(all_x), min(all_y), max(all_r), max(all_b)
        max_fh = max([f[3] for f in faces])

        m_top = int(max_fh * 0.5)
        m_bottom = int(max_fh * 1.5)
        m_side = int(max_fh * 0.5)

        return (max(0, ux1-m_side), max(0, uy1-m_top), min(img_w, ux2+m_side), min(img_h, uy2+m_bottom))

    def verify_cropped_image(self, cropped_img, original_face_count):
        w, h = cropped_img.size
        # Re-detect faces on the crop
        # Note: Depending on optimization, we might want to skip re-detection or re-init detector if needed
        # For now, let's create a temp detector or resize logic inside detect_faces_yunet handles it
        post_faces = self.detect_faces_yunet(cropped_img)

        if original_face_count > 0:
            if not post_faces or len(post_faces) < (original_face_count * 0.5):
                return False, "Face lost"

        margin_y = int(h * 0.02)
        margin_x = int(w * 0.02)

        if post_faces:
            for face in post_faces:
                fx, fy, fw, fh = face
                if fy < margin_y: return False, "Top cut"
                if (h - (fy + fh)) < int(fh * 0.6): return False, "Neck cut"
                if fx < margin_x: return False, "Left cut"
                if fx + fw > w - margin_x: return False, "Right cut"

        return True, "OK"

    def process_contain_mode(self, img, target_w, target_h, reason=""):
        src_w, src_h = img.size
        ratio = min(target_w / src_w, target_h / src_h)
        new_w, new_h = int(src_w * ratio), int(src_h * ratio)
        img_res = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        bg = self.get_edge_most_common_color(img, is_logo=False)

        self.last_process_log = f"【全体表示】{src_w}x{src_h} -> {new_w}x{new_h} / 理由:{reason}"

        canvas = Image.new("RGB", (target_w, target_h), bg)
        canvas.paste(img_res, ((target_w - new_w) // 2, (target_h - new_h) // 2))
        return canvas

    def process_square_fallback(self, img, faces, safe_zone, target_w, target_h, prev_reason):
        img_w, img_h = img.size

        sq_size = min(img_w, img_h)
        sx1, sy1, sx2, sy2 = safe_zone

        if (sx2 - sx1) > sq_size or (sy2 - sy1) > sq_size:
            return self.process_contain_mode(img, target_w, target_h, f"正方形処理失敗({prev_reason})")

        if len(faces) == 1:
            fx, fy, fw, fh = faces[0]
            cx = fx + fw // 2
            target_y1_ideal = fy - int(sq_size * 0.20)
        else:
            group_min_x = min([f[0] for f in faces])
            group_max_x = max([f[0] + f[2] for f in faces])
            cx = (group_min_x + group_max_x) // 2

            top_y = min([f[1] for f in faces])
            target_y1_ideal = top_y - int(sq_size * 0.20)

        sq_x1 = cx - sq_size // 2
        sq_y1 = target_y1_ideal

        sq_x1 = max(0, min(sq_x1, img_w - sq_size))
        sq_y1 = max(0, min(sq_y1, img_h - sq_size))

        if sq_x1 > sx1: sq_x1 = sx1
        if sq_x1 + sq_size < sx2: sq_x1 = sx2 - sq_size
        if sq_y1 > sy1: sq_y1 = sy1
        if sq_y1 + sq_size < sy2: sq_y1 = sy2 - sq_size

        sq_x1 = int(max(0, min(sq_x1, img_w - sq_size)))
        sq_y1 = int(max(0, min(sq_y1, img_h - sq_size)))
        sq_x2 = sq_x1 + sq_size
        sq_y2 = sq_y1 + sq_size

        sq_crop = img.crop((sq_x1, sq_y1, sq_x2, sq_y2))

        is_valid, reason = self.verify_cropped_image(sq_crop, len(faces))

        if is_valid:
            ratio = min(target_w / sq_size, target_h / sq_size)
            new_w, new_h = int(sq_size * ratio), int(sq_size * ratio)
            img_res = sq_crop.resize((new_w, new_h), Image.Resampling.LANCZOS)

            bg = self.get_edge_most_common_color(sq_crop, is_logo=False)
            self.last_process_log = f"【正方形代替処理】理由:{prev_reason} / 背景色:{bg}"

            canvas = Image.new("RGB", (target_w, target_h), bg)
            canvas.paste(img_res, ((target_w - new_w) // 2, (target_h - new_h) // 2))
            return canvas
        else:
            return self.process_contain_mode(img, target_w, target_h, f"正方形検証NG({reason}) -> 全体表示")

    def process_photo_smart(self, img, target_w, target_h):
        img = ImageOps.exif_transpose(img)

        if self.config.get("force_contain_mode", False):
            return self.process_contain_mode(img, target_w, target_h, "強制全体表示")

        img_w, img_h = img.size
        # Protection against 0 devision
        if target_h == 0: target_h = 600
        target_ratio = target_w / target_h

        faces = self.detect_faces_yunet(img)
        safe_zone = self.calculate_safe_zone(faces, img_w, img_h)

        if (img_w / img_h) > target_ratio:
            crop_w, crop_h = int(img_h * target_ratio), img_h
        else:
            crop_w, crop_h = img_w, int(img_w / target_ratio)

        if not safe_zone:
            x1, y1 = (img_w - crop_w) // 2, (img_h - crop_h) // 2
            self.last_process_log = f"【中央切り抜き】{img_w}x{img_h} -> ({x1},{y1}) / 顔検出なし"
            return img.crop((x1, y1, x1 + crop_w, y1 + crop_h)).resize((target_w, target_h), Image.Resampling.LANCZOS)

        sx1, sy1, sx2, sy2 = safe_zone

        if (sx2 - sx1) > crop_w or (sy2 - sy1) > crop_h:
            return self.process_square_fallback(img, faces, safe_zone, target_w, target_h, "顔が範囲外")

        # --- One Face ---
        if len(faces) == 1:
            fx, fy, fw, fh = faces[0]

            base_x1 = (img_w - crop_w) // 2
            x1 = max(0, min(base_x1, img_w - crop_w))
            if x1 > sx1: x1 = sx1
            if x1 + crop_w < sx2: x1 = sx2 - crop_w
            x1 = int(max(0, min(x1, img_w - crop_w)))
            x2 = x1 + crop_w

            neck_bottom = fy + fh + int(fh * 0.8)
            safe_y1_min = max(0, neck_bottom - crop_h)
            safe_y1_max = min(img_h - crop_h, max(0, fy - int(fh * 0.2)))

            if safe_y1_min > safe_y1_max:
                return self.process_square_fallback(img, faces, safe_zone, target_w, target_h, "首切れ防止失敗")

            target_y1_ideal = fy - int(crop_h * 0.15)
            y1 = int(max(safe_y1_min, min(target_y1_ideal, safe_y1_max)))
            y2 = y1 + crop_h

            test_crop = img.crop((x1, y1, x2, y2)).resize((target_w, target_h), Image.Resampling.LANCZOS)
            is_valid, reason = self.verify_cropped_image(test_crop, 1)

            if is_valid:
                self.last_process_log = f"【スマート単独】OK"
                return test_crop
            else:
                return self.process_square_fallback(img, faces, safe_zone, target_w, target_h, f"検証NG({reason})")

        # --- Multi Face ---
        group_min_x = min([f[0] for f in faces])
        group_max_x = max([f[0] + f[2] for f in faces])
        group_cx = (group_min_x + group_max_x) // 2

        base_x1 = group_cx - (crop_w // 2)
        x1 = max(0, min(base_x1, img_w - crop_w))

        if x1 > group_min_x: x1 = group_min_x
        if x1 + crop_w < group_max_x: x1 = group_max_x - crop_w
        x1 = int(max(0, min(x1, img_w - crop_w)))
        x2 = x1 + crop_w

        top_y = min([f[1] for f in faces])
        group_bottom = max([f[1] + int(f[3] * 1.8) for f in faces])

        safe_y1_min = max(0, group_bottom - crop_h)
        safe_y1_max = min(img_h - crop_h, max(0, top_y - int(crop_h * 0.05)))

        if safe_y1_min > safe_y1_max:
            return self.process_square_fallback(img, faces, safe_zone, target_w, target_h, "複数顔間隔失敗")

        target_y1_ideal = top_y - int(crop_h * 0.10)

        y1 = int(max(safe_y1_min, min(target_y1_ideal, safe_y1_max)))
        y2 = y1 + crop_h

        test_crop = img.crop((x1, y1, x2, y2)).resize((target_w, target_h), Image.Resampling.LANCZOS)

        is_valid, reason = self.verify_cropped_image(test_crop, len(faces))

        if is_valid:
            self.last_process_log = f"【スマート複数】OK"
            return test_crop
        else:
            return self.process_square_fallback(img, faces, safe_zone, target_w, target_h, f"検証NG({reason})")

    def create_drive_folder(self, folder_name, parent_id):
        file_metadata = {'name': folder_name, 'mimeType': 'application/vnd.google-apps.folder', 'parents': [parent_id]}
        file = self.service_drive.files().create(body=file_metadata, fields='id').execute()
        return file.get('id')

    def upload_image_to_drive(self, pil_img, file_name, parent_id, fmt="JPEG"):
        output = io.BytesIO()
        save_fmt = "JPEG" if fmt.upper() == "JPG" else fmt.upper()
        if save_fmt == "JPEG" and pil_img.mode == "RGBA": pil_img = pil_img.convert("RGB")
        
        pil_img.save(output, format=save_fmt, quality=95)
        output.seek(0)
        
        media = MediaIoBaseUpload(output, mimetype="image/png" if save_fmt=="PNG" else "image/jpeg", resumable=True)
        file = self.service_drive.files().create(body={'name': file_name, 'parents': [parent_id]}, media_body=media, fields='id').execute()
        f_id = file.get('id')
        direct_link = f"https://drive.google.com/thumbnail?id={f_id}&sz=w400"
        return f_id, direct_link

    def run_process(self):
        try:
            self.status = "running"
            self.log("バックグラウンド処理を開始しました...")
            self.authenticate()
            self.log("Google認証に成功しました。")

            timestamp = datetime.now().strftime("%Y%m%d_%H%M")
            project_title = self.config["project_name"]
            
            self.log(f"出力フォルダを作成中: {project_title}...")
            run_folder_id = self.create_drive_folder(f"【{project_title}】_{timestamp}", self.config["output_root_folder_id"])
            self.log(f"出力フォルダを作成完了 (ID: {run_folder_id})")
            
            if self.config["spreadsheet_id"]:
                self.log(f"スプレッドシートを開いています (ID: {self.config['spreadsheet_id']})...")
                ss = self.service_sheets.open_by_key(self.config["spreadsheet_id"])
                
                self.log("新しいワークシートを作成中...")
                worksheet = ss.add_worksheet(title=f"{project_title}_{timestamp}", rows="100", cols="7")
                
                self.log("ヘッダー行を書き込み中...")
                worksheet.append_row(["プレビュー", "ファイル名", "詳細処理内容", "種類", "ファイルID", "URL", "処理日時"])
                self.log("スプレッドシートの準備が完了しました。")
            else:
                ss = None
                worksheet = None

            records = []
             
            mode = self.config.get("processing_mode", "photos")
            input_id = self.config.get("input_folder_id")

            if input_id:
                self.log(f"ソースフォルダをスキャン中 (モード: {mode}, ID: {input_id})...")
                self.process_folder(input_id, run_folder_id, mode, records)
            else:
                self.log("警告: ソースフォルダIDが指定されていません。")

            if records and worksheet:
                worksheet.append_rows(records, value_input_option='USER_ENTERED')
                
                # Format Sheet
                try:
                    sheet_id = worksheet.id
                    ss.batch_update({"requests": [
                        {"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "ROWS", "startIndex": 1, "endIndex": len(records)+1}, "properties": {"pixelSize": 120}, "fields": "pixelSize"}},
                        {"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 1}, "properties": {"pixelSize": 180}, "fields": "pixelSize"}},
                        {"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 2, "endIndex": 3}, "properties": {"pixelSize": 450}, "fields": "pixelSize"}}
                    ]})
                except Exception as e:
                    self.log(f"警告: シートの整形に失敗しました: {e}")
            
            self.result_links = {
                "drive_folder": f"https://drive.google.com/drive/folders/{run_folder_id}",
                "spreadsheet": f"https://docs.google.com/spreadsheets/d/{self.config['spreadsheet_id']}" if self.config["spreadsheet_id"] else ""
            }
            if self.stop_requested:
                self.status = "stopped"
                self.log("処理が中断されました。")
            else:
                self.status = "completed"
                self.log("処理が完了しました！")

        except Exception as e:
            self.log(f"エラーが発生しました: {str(e)}")
            self.status = "error"
            import traceback
            traceback.print_exc()

    def process_folder(self, input_id, parent_out_id, type_name, records):
        out_sub_id = self.create_drive_folder(type_name, parent_out_id)
        
        query = f"'{input_id}' in parents and mimeType contains 'image/' and trashed = false"
        files = self.service_drive.files().list(q=query).execute().get('files', [])

        self.total_files += len(files)

        for i, f_info in enumerate(files):
            if self.stop_requested:
                self.log("停止リクエストを受信しました。処理を中断します。")
                break
            
            self.processed_count += 1
            
            img_name = f_info['name']
            self.log(f"処理中 ({self.processed_count}/{self.total_files}): {img_name}")
            try:
                request = self.service_drive.files().get_media(fileId=f_info['id'])
                fh = io.BytesIO()
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while not done: _, done = downloader.next_chunk()
                fh.seek(0)
                img = Image.open(fh)

                # Process based on type
                target_w = int(self.config["width"])
                target_h = int(self.config["height"])

                if type_name == "photos":
                    res = self.process_photo_smart(img, target_w, target_h)
                    fmt = "JPEG"
                else: # logos
                    res = self.process_logo_smart(
                        img, 
                        target_w, 
                        target_h,
                        safe_area=float(self.config.get("logo_safe_area", 0.8)),
                        fmt="PNG"
                    )
                    fmt = "PNG"
                
                new_id, direct_link = self.upload_image_to_drive(res, img_name, out_sub_id, fmt)
                
                records.append([
                    f'=IMAGE("{direct_link}")', 
                    img_name, 
                    self.last_process_log, 
                    type_name, 
                    new_id, 
                    f"https://drive.google.com/file/d/{new_id}/view", 
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                ])
                
            except Exception as e:
                self.log(f"エラー ({img_name}): {e}")

