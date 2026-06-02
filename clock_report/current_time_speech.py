from datetime import datetime
import os


def save_current_time_text(output_filename='time_speech.txt'):
    print('現在時刻を取得しています...')

    now = datetime.now()
    speech_text = f'現在の時刻は、{now.hour}時{now.minute}分だよ。'

    print(f'読み上げ用テキストを作成しました: {speech_text}')
    print(f'保存先ファイル: {os.path.abspath(output_filename)}')

    try:
        with open(output_filename, 'w', encoding='utf-8') as file:
            file.write(speech_text)
        print('ファイルの保存が完了しました。')
    except OSError as error:
        print(f'ファイルの保存中にエラーが発生しました: {error}')


if __name__ == '__main__':
    save_current_time_text()
