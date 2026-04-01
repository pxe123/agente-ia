import os
import numpy as np
from PIL import Image


INPUT = r"C:\Users\Ricardo De Tomasi\.cursor\projects\c-Users-Ricardo-De-Tomasi-Documents-app-agente-ia\assets\c__Users_Ricardo_De_Tomasi_AppData_Roaming_Cursor_User_workspaceStorage_6a1293b8487c2fffb063cbb142c7869d_images_Avi_o_de_papel_202603251734-1dedcf38-49a2-42f2-99f5-22e7a476735f.png"
OUTPUT = r"C:\Users\Ricardo De Tomasi\Documents\app\agente-ia\panel\static\images\logo.png"


def remove_dark_background(input_path: str, output_path: str) -> None:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    img = Image.open(input_path).convert("RGBA")
    arr = np.array(img)
    rgb = arr[..., :3].astype(np.float32)

    # "Cor" aproximada: quão diferente é cada canal
    chroma = rgb.max(axis=-1) - rgb.min(axis=-1)

    # Luminância aproximada
    lum = 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]

    alpha = arr[..., 3].astype(np.float32)

    # Thresholds para remover o fundo escuro (preto) sem destruir bordas.
    chroma_thr = 18.0
    lum0 = 8.0   # abaixo disso -> transparente total
    lum1 = 55.0  # entre lum0..lum1 faz fade

    mask_low_chroma = chroma <= chroma_thr
    factor = (lum - lum0) / (lum1 - lum0)
    factor = np.clip(factor, 0.0, 1.0)

    alpha_new = alpha.copy()
    alpha_new[mask_low_chroma] = alpha_new[mask_low_chroma] * factor[mask_low_chroma]
    alpha_new[(mask_low_chroma) & (lum < lum0)] = 0.0

    arr[..., 3] = np.round(alpha_new).astype(np.uint8)

    out_img = Image.fromarray(arr, mode="RGBA")
    out_img.save(output_path, format="PNG", optimize=True)


if __name__ == "__main__":
    remove_dark_background(INPUT, OUTPUT)
    print("Logo salvo em:", OUTPUT)

